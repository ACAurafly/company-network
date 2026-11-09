using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace CompanyNetwork
{
    // Process-local, bounded journal. Raw engine output and progress text never enter it.
    internal static class Diagnostics
    {
        static readonly object Sync = new object();
        static readonly Stopwatch Clock = Stopwatch.StartNew();
        static readonly Queue<object> Events = new Queue<object>();
        static long PreviousStageMs;

        internal static void Record(string kind, object detail)
        {
            lock (Sync)
            {
                long elapsed = Clock.ElapsedMilliseconds;
                long? stageElapsed = null;
                if (kind == "phase" || kind == "transition")
                {
                    stageElapsed = elapsed - PreviousStageMs;
                    PreviousStageMs = elapsed;
                }
                Events.Enqueue(new { kind = kind, elapsedMs = elapsed, previousStageElapsedMs = stageElapsed, utc = DateTime.UtcNow.ToString("o"), detail = detail });
                while (Events.Count > 256) Events.Dequeue();
            }
        }

        internal static void Failure(string operation, Exception error)
        {
            AppProblem problem = Program.Explain(error);
            Record("error", new { operation = operation, code = problem.Code, nativeError = problem.NativeError });
        }

        internal static string Redact(string value)
        {
            if (value == null) return null;
            value = Regex.Replace(value, @"\b[a-z][a-z0-9+.-]*://[^\s""<>]+", delegate(Match match) {
                Uri uri;
                if (!Uri.TryCreate(match.Value, UriKind.Absolute, out uri)) return "[redacted-url]";
                // Paths can contain document ids and login tokens; keep only the origin.
                return uri.Scheme + "://" + uri.Host + (uri.IsDefaultPort ? "" : ":" + uri.Port) + "/[redacted-path]";
            }, RegexOptions.IgnoreCase);
            value = Regex.Replace(value, @"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?", "[redacted-token]");
            value = Regex.Replace(value, @"[^\s;=/@:]+:[^\s;@]+@", "[redacted-userinfo]@");
            value = Regex.Replace(value, @"(?i)\b(password|passwd|username|authorization|proxy-authorization|cookie|set-cookie|token|secret)\s*[:=]\s*[^\r\n]+", "$1=[redacted]");
            if (!String.IsNullOrEmpty(Environment.UserName)) value = Regex.Replace(value, Regex.Escape(Environment.UserName), "[user]", RegexOptions.IgnoreCase);
            return value;
        }

        static object Clean(object value)
        {
            string text = value as string;
            if (text != null) return Redact(text);
            IDictionary<string, object> map = value as IDictionary<string, object>;
            if (map != null)
            {
                var result = new Dictionary<string, object>();
                foreach (var pair in map)
                    result[Redact(pair.Key)] = Regex.IsMatch(pair.Key, "(?i)password|username|authorization|cookie|token|secret") ? "[redacted]" : Clean(pair.Value);
                return result;
            }
            IEnumerable sequence = value as IEnumerable;
            if (sequence != null)
            {
                var result = new List<object>();
                foreach (object item in sequence) result.Add(Clean(item));
                return result;
            }
            return value;
        }

        internal static string Collect(Func<ConnectionSnapshot> read, IDictionary<string, Func<object>> collectors)
        {
            var data = new Dictionary<string, object>();
            data["schemaVersion"] = 1;
            data["version"] = Assembly.GetExecutingAssembly().GetName().Version.ToString();
            data["utc"] = DateTime.UtcNow.ToString("o");
            data["localTime"] = DateTimeOffset.Now.ToString("o");
            data["businessValidation"] = "未验收：VPN 就绪不代表飞书消息、文档、GPT 或内网业务已通过。";
            var sections = new Dictionary<string, Func<object>>(collectors);
            sections["vpn"] = delegate {
                ConnectionSnapshot state = read();
                return new { state = state.Kind, outerActive = state.Outer, innerActive = state.Inner, routeReady = state.Route, sessionsReady = state.SessionsReady };
            };
            foreach (var section in sections)
            {
                try { data[section.Key] = new { ok = true, value = section.Value() }; }
                catch (Exception error)
                {
                    AppProblem problem = Program.Explain(error);
                    data[section.Key] = new { ok = false, code = problem.Code, nativeError = problem.NativeError };
                }
            }
            lock (Sync) data["timeline"] = Events.ToArray();
            var json = AppPayload.Json();
            return json.Serialize(Clean(json.DeserializeObject(json.Serialize(data))));
        }

        internal static string Collect(Func<ConnectionSnapshot> read)
        {
            return Collect(read, new Dictionary<string, Func<object>> {
                { "interfacesAndDns", Interfaces }, { "routes", Routes },
                { "systemProxy", Proxy }, { "runningNetworkSoftware", Software }
            });
        }

        static object Interfaces()
        {
            var result = new List<object>();
            foreach (NetworkInterface adapter in NetworkInterface.GetAllNetworkInterfaces())
            {
                try
                {
                    IPInterfaceProperties properties = adapter.GetIPProperties();
                    var addresses = new List<string>();
                    foreach (UnicastIPAddressInformation address in properties.UnicastAddresses) addresses.Add(address.Address.ToString());
                    var dns = new List<string>();
                    foreach (var address in properties.DnsAddresses) dns.Add(address.ToString());
                    result.Add(new { name = adapter.Name, type = adapter.NetworkInterfaceType.ToString(), status = adapter.OperationalStatus.ToString(), addresses = addresses, dns = dns,
                        possibleTun = Regex.IsMatch(adapter.Name + " " + adapter.Description, "(?i)tun|tap|wintun|mihomo|clash|vpn"), tunNote = "名称推断；不是运行冲突结论" });
                }
                catch { result.Add(new { name = adapter.Name, error = "interface_query_failed" }); }
            }
            return result;
        }

        static object Routes()
        {
            // Read-only command, bounded wait; no raw output is exported.
            using (Process process = Process.Start(new ProcessStartInfo {
                FileName = Path.Combine(Environment.SystemDirectory, "route.exe"), Arguments = "print",
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true
            }))
            {
                var output = process.StandardOutput.ReadToEndAsync();
                if (!process.WaitForExit(5000)) { process.Kill(); throw new IOException(); }
                if (process.ExitCode != 0) throw new IOException();
                var rows = new List<string>();
                foreach (string line in output.Result.Split('\n'))
                    if (Regex.IsMatch(line, @"^\s*(?:\d{1,3}\.){3}\d{1,3}\s+(?:\d{1,3}\.){3}\d{1,3}\s+") ||
                        Regex.IsMatch(line, @"^\s*\d+\s+\d+\s+[0-9a-fA-F:]+/\d+\s+")) rows.Add(line.Trim());
                return rows;
            }
        }

        static object Proxy()
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Internet Settings"))
                return new { enabled = key == null ? null : key.GetValue("ProxyEnable"), server = key == null ? null : key.GetValue("ProxyServer"), pac = key == null ? null : key.GetValue("AutoConfigURL"),
                    note = "当前用户 Internet Settings；不代表 WinHTTP、应用自有代理或 TUN 的全部流量" };
        }

        static object Software()
        {
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (Process process in Process.GetProcesses())
            {
                using (process)
                {
                    try
                    {
                        string name = process.ProcessName;
                        if (Regex.IsMatch(name, "(?i)^(clash.*|mihomo.*|sing-box|v2ray.*|xray|vpnclient.*|wireguard.*|openvpn.*|tailscale.*)$")) names.Add(name);
                    }
                    catch { }
                }
            }
            return new { processNames = new List<string>(names), note = "仅进程名；不采集命令行、账号或原始会话输出。运行不等于冲突。" };
        }
    }
}
