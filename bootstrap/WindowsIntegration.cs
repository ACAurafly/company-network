using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32;

namespace CompanyNetwork
{
    internal sealed class CommandResult
    {
        internal int ExitCode;
        internal string Output;
    }

    internal static class Processes
    {
        internal static string Quote(string value)
        {
            StringBuilder result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); slashes = 0; continue; }
                result.Append('\\', slashes); slashes = 0; result.Append(c);
            }
            result.Append('\\', slashes * 2); result.Append('"');
            return result.ToString();
        }

        internal static CommandResult Run(string file, string arguments, int timeoutMs)
        {
            ProcessStartInfo start = new ProcessStartInfo(file, arguments);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.WorkingDirectory = Path.GetDirectoryName(file);
            using (Process process = Process.Start(start))
            {
                process.StandardInput.Close();
                Task<string> output = process.StandardOutput.ReadToEndAsync();
                Task<string> error = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(timeoutMs))
                {
                    try { process.Kill(); } catch (InvalidOperationException) { }
                    throw new AppProblem("client_timeout", "客户端响应超时，请稍后重试或联系管理员。");
                }
                if (!Task.WaitAll(new Task[] { output, error }, 5000))
                    throw new AppProblem("client_timeout", "客户端未能完成准备，请稍后重试。");
                // Command output stays in memory. It may contain the employee's account identity.
                return new CommandResult { ExitCode = process.ExitCode, Output = output.Result };
            }
        }

        internal static bool IsAdministrator()
        {
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
        }
    }

    internal sealed class Engine
    {
        internal const string ServiceName = "SEVPNCLIENT";
        internal string ServiceExe;
        internal string DirectoryPath;
        internal string Cli;
        internal string Manager;
        internal bool Reused;

        internal static string OwnedDirectory
        {
            get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "CompanyNetwork", "Client"); }
        }

        internal static Engine Find()
        {
            string image;
            using (RegistryKey key = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\" + ServiceName, false))
            {
                if (key == null) return null;
                image = key.GetValue("ImagePath", null, RegistryValueOptions.DoNotExpandEnvironmentNames) as string;
            }
            if (String.IsNullOrWhiteSpace(image)) throw ExistingProblem();
            image = Environment.ExpandEnvironmentVariables(image.Trim());
            Match match = Regex.Match(image, "^\"([^\"]+)\"(?:\\s|$)");
            if (!match.Success) match = Regex.Match(image, @"^(.+?\.exe)(?:\s|$)", RegexOptions.IgnoreCase);
            if (!match.Success) throw ExistingProblem();
            string path = match.Groups[1].Value;
            if (path.StartsWith(@"\??\", StringComparison.Ordinal)) path = path.Substring(4);
            if (!Path.IsPathRooted(path) || !File.Exists(path) ||
                !Regex.IsMatch(Path.GetFileName(path), @"\Avpnclient(?:_x64)?\.exe\z", RegexOptions.IgnoreCase))
                throw ExistingProblem();
            Engine engine = new Engine();
            engine.ServiceExe = Path.GetFullPath(path);
            engine.DirectoryPath = Path.GetDirectoryName(engine.ServiceExe);
            bool x64 = Path.GetFileNameWithoutExtension(path).EndsWith("_x64", StringComparison.OrdinalIgnoreCase);
            engine.Cli = engine.Tool("vpncmd", x64);
            engine.Manager = engine.Tool("vpncmgr", x64);
            if (!File.Exists(Path.Combine(engine.DirectoryPath, "hamcore.se2"))) throw ExistingProblem();
            engine.Reused = !String.Equals(engine.DirectoryPath.TrimEnd('\\'), OwnedDirectory.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
            return engine;
        }

        private string Tool(string name, bool x64)
        {
            string preferred = Path.Combine(DirectoryPath, name + (x64 ? "_x64.exe" : ".exe"));
            string alternate = Path.Combine(DirectoryPath, name + (x64 ? ".exe" : "_x64.exe"));
            if (File.Exists(preferred)) return preferred;
            if (File.Exists(alternate)) return alternate;
            throw ExistingProblem();
        }

        private static AppProblem ExistingProblem()
        {
            return new AppProblem("existing_client_unusable", "检测到已有客户端，但组件不完整。请联系管理员修复原客户端后重试。");
        }

        internal static string ServiceStatus()
        {
            using (ServiceController service = new ServiceController(ServiceName))
            {
                try { service.Refresh(); return service.Status.ToString(); }
                catch (InvalidOperationException) { return "NotInstalled"; }
            }
        }

        internal CommandResult Command(string command, int timeoutMs)
        {
            return Processes.Run(Cli, "localhost /CLIENT /CMD " + command, timeoutMs);
        }

        internal void RequireRpc()
        {
            if (ServiceStatus() != "Running" || Command("NicList", 10000).ExitCode != 0)
                throw new AppProblem("client_not_ready", "客户端尚未准备完成。若原客户端设置过管理密码，请联系管理员完成配置。");
        }

        internal void EnsureNic()
        {
            EnsureNic("VPN");
            EnsureNic("VPN2");
        }

        private void EnsureNic(string name)
        {
            EnsureNic(name, delegate(string command) {
                return Command(command, command.StartsWith("NicCreate", StringComparison.Ordinal) ? 90000 : 10000).ExitCode;
            }, EnsureUiHelper);
        }

        internal static void EnsureNic(Func<string, int> command, Action prepareHelper)
        {
            EnsureNic("VPN", command, prepareHelper);
        }

        internal static void EnsureNic(string name, Func<string, int> command, Action prepareHelper)
        {
            if (name != "VPN" && name != "VPN2") throw new InvalidDataException("Unsupported adapter.");
            int query = command("NicGetSetting " + name);
            if (query == 0) return;
            // CtGetVLan reports ERR_OBJECT_NOT_FOUND (29), not ERR_NOT_SUPPORTED (33).
            if (query != 29) throw new AppProblem("adapter_query_failed", "无法读取网络组件（错误码 " + query + "），请联系管理员检查客户端。", query);
            // On Vista and later, CtCreateVLan delegates the signed driver installation
            // to the interactive UI helper over localhost:9983. A newly installed
            // service does not start that helper. Reusing an existing client hid this.
            prepareHelper();
            int create = command("NicCreate " + name);
            if (create != 0 && create != 30)
                throw AdapterInstallProblem(create);
            if (command("NicGetSetting " + name) != 0)
                throw new AppProblem("adapter_not_ready", "网络组件尚未就绪，请稍后重试。");
        }

        internal static AppProblem AdapterInstallProblem(int nativeError)
        {
            return new AppProblem("adapter_install_failed", "虚拟网卡安装失败（SoftEther 错误码 " + nativeError + "）。请确认 Windows 管理员提示；若仍失败，把此错误码发给管理员。", nativeError);
        }

        internal static bool UiHelperReady()
        {
            try
            {
                using (TcpClient probe = new TcpClient(AddressFamily.InterNetwork))
                {
                    IAsyncResult pending = probe.BeginConnect(IPAddress.Loopback, 9983, null, null);
                    using (WaitHandle completed = pending.AsyncWaitHandle)
                    {
                        if (!completed.WaitOne(500)) return false;
                        probe.EndConnect(pending);
                        return true;
                    }
                }
            }
            catch (SocketException) { return false; }
        }

        internal void EnsureUiHelper()
        {
            if (UiHelperReady()) return;
            ProcessStartInfo start = new ProcessStartInfo(ServiceExe, "/uihelp");
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WorkingDirectory = DirectoryPath;
            // This is a resident official helper. Dispose only the process handle;
            // waiting for exit (or killing it on timeout) would break installation.
            using (Process helper = Process.Start(start))
            {
                DateTime deadline = DateTime.UtcNow.AddSeconds(15);
                while (DateTime.UtcNow < deadline)
                {
                    if (UiHelperReady()) return;
                    Thread.Sleep(250);
                }
            }
            throw new AppProblem("ui_helper_unavailable", "驱动安装辅助程序未能启动。请确认安全软件是否阻止了官方 SoftEther 程序，并把此提示发给管理员。");
        }

        internal bool AccountExists(string name)
        {
            int code = Command("AccountGet " + Processes.Quote(name), 10000).ExitCode;
            if (code == 0) return true;
            if (code == 36) return false;
            throw new AppProblem("account_query_failed", "无法读取连接配置，请联系管理员检查客户端。");
        }

        internal void StartManager(string profile)
        {
            ProcessStartInfo start = new ProcessStartInfo(Manager, "/easy" + (profile == null ? "" : " " + Processes.Quote(profile)));
            start.WorkingDirectory = DirectoryPath;
            start.UseShellExecute = false;
            using (Process process = Process.Start(start)) { }
        }

        internal static Engine Ensure(AppPayload payload, bool allowElevation)
        {
            Engine existing = Find();
            if (existing == null || ServiceStatus() != "Running")
            {
                if (!allowElevation)
                    throw new AppProblem("needs_install", "需要先安装或启动网络组件。请打开应用并选择“安装并连接”。");
                if (Processes.IsAdministrator()) Install(payload);
                else
                {
                    ProcessStartInfo start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "--install-engine");
                    start.UseShellExecute = true;
                    start.Verb = "runas";
                    using (Process process = Process.Start(start))
                    {
                        if (!process.WaitForExit(180000))
                            throw new AppProblem("installation_pending", "网络组件仍在安装，请稍后重新打开应用。");
                        if (process.ExitCode >= 1000 && process.ExitCode < 2000)
                            throw AdapterInstallProblem(process.ExitCode - 1000);
                        if (process.ExitCode == 900)
                            throw new AppProblem("ui_helper_unavailable", "驱动安装辅助程序未能启动，请把此提示发给管理员。");
                        if (process.ExitCode != 0)
                            throw new AppProblem("installation_failed", "网络组件安装未完成，请允许管理员确认后重试。");
                    }
                }
                existing = Find();
            }
            if (existing == null) throw new AppProblem("engine_missing", "网络组件尚未安装成功，请联系管理员。");
            existing.RequireRpc();
            if (allowElevation) existing.EnsureNic();
            else if (existing.Command("NicGetSetting VPN", 10000).ExitCode != 0 ||
                existing.Command("NicGetSetting VPN2", 10000).ExitCode != 0)
                throw new AppProblem("needs_install", "需要先安装网络组件，请选择“安装并连接”。");
            return existing;
        }

        internal static void Install(AppPayload payload)
        {
            payload.RequireActive();
            if (!Processes.IsAdministrator()) throw new AppProblem("administrator_required", "安装网络组件需要管理员确认。");
            using (Mutex gate = new Mutex(false, @"Global\CompanyNetwork.Engine.Install"))
            {
                bool acquired;
                try { acquired = gate.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new AppProblem("installation_busy", "另一项安装正在进行，请稍后重试。");
                try
                {
                    Engine engine = Find();
                    if (engine == null)
                    {
                        RejectReparsePoints(OwnedDirectory);
                        System.IO.Directory.CreateDirectory(OwnedDirectory);
                        foreach (string name in BootstrapCore.EngineFiles)
                        {
                            string target = Path.Combine(OwnedDirectory, name);
                            byte[] bytes = payload.Files["engine/" + name];
                            if (File.Exists(target))
                            {
                                if (!SameBytes(target, bytes))
                                    throw new AppProblem("engine_directory_conflict", "安装目录内存在不同版本的文件，请联系管理员处理。");
                                continue;
                            }
                            using (FileStream file = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                                file.Write(bytes, 0, bytes.Length);
                        }
                        // Recheck after extraction: an independently installed client always wins.
                        engine = Find();
                        if (engine == null)
                        {
                            Processes.Run(Path.Combine(OwnedDirectory, "vpnclient_x64.exe"), "/install /silent", 60000);
                            engine = Find();
                        }
                    }
                    if (engine == null) throw new AppProblem("service_install_failed", "网络服务未能安装，请联系管理员。");
                    if (ServiceStatus() != "Running") Processes.Run(engine.ServiceExe, "/start /silent", 30000);
                    DateTime deadline = DateTime.UtcNow.AddSeconds(45);
                    bool ready = false;
                    while (DateTime.UtcNow < deadline)
                    {
                        if (ServiceStatus() == "Running" && engine.Command("NicList", 5000).ExitCode == 0) { ready = true; break; }
                        Thread.Sleep(750);
                    }
                    if (!ready) throw new AppProblem("service_rpc_unavailable", "网络服务尚未响应，请稍后重试或联系管理员。");
                    engine.EnsureNic();
                }
                finally { gate.ReleaseMutex(); }
            }
        }

        private static void RejectReparsePoints(string path)
        {
            DirectoryInfo current = new DirectoryInfo(path);
            while (current != null)
            {
                if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new AppProblem("unsafe_install_directory", "安装目录不能是重定向目录，请联系管理员处理。");
                current = current.Parent;
            }
        }

        internal static bool SameBytes(string path, byte[] bytes)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] expected = sha.ComputeHash(bytes);
                using (FileStream file = File.OpenRead(path))
                    return BootstrapCore.Hex(expected) == BootstrapCore.Hex(sha.ComputeHash(file));
            }
        }
    }

    public sealed class InstallState
    {
        public string AccountName { get; set; }
        public string OwnerSid { get; set; }
        public bool AccountOwned { get; set; }
        public bool CaAdded { get; set; }
        public string CaSha256 { get; set; }
        public string TransportAccountName { get; set; }
        public bool TransportOwned { get; set; }
        public int ConfigurationVersion { get; set; }
    }

    internal sealed class UserInstall
    {
        internal readonly AppPayload Payload;
        internal readonly string Sid;
        internal readonly string Account;
        internal readonly string TransportAccount;
        internal readonly string TransportPath;
        internal readonly string ServerCertPath;
        internal readonly string DirectoryPath;
        internal readonly string Launcher;
        internal readonly string ProfilePath;
        internal readonly string StatePath;
        internal InstallState State;
        internal Action CheckCancelled = delegate {};

        internal UserInstall(AppPayload payload)
        {
            Payload = payload;
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent()) Sid = identity.User.Value;
            Account = BootstrapCore.AccountName(payload.AccountPrefix, Sid);
            TransportAccount = BootstrapCore.AccountName("CompanyTransport", Sid);
            DirectoryPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CompanyNetwork");
            Launcher = Path.Combine(DirectoryPath, "CompanyNetwork.exe");
            ProfilePath = Path.Combine(DirectoryPath, "profile.vpn");
            TransportPath = Path.Combine(DirectoryPath, "transport.vpn");
            ServerCertPath = Path.Combine(DirectoryPath, "server-pin.cer");
            StatePath = Path.Combine(DirectoryPath, "state.json");
            ReloadState();
        }

        internal void ReloadState()
        {
            State = null;
            if (File.Exists(StatePath))
            {
                State = AppPayload.Json().Deserialize<InstallState>(File.ReadAllText(StatePath, Encoding.UTF8));
                if (State == null || State.AccountName != Account || State.OwnerSid != Sid ||
                    State.CaSha256 != BootstrapCore.ExpectedCaSha256 ||
                    (State.TransportAccountName != null && State.TransportAccountName != TransportAccount) ||
                    (State.TransportOwned && State.TransportAccountName != TransportAccount))
                    throw new AppProblem("state_conflict", "本机存在不同的应用配置，请联系管理员确认后再更新。");
            }
        }

        internal void SaveState()
        {
            AtomicText(StatePath, AppPayload.Json().Serialize(State));
        }

        private static void AtomicText(string path, string value)
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".new";
            try
            {
                File.WriteAllText(temporary, value, new UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private void SaveFiles()
        {
            System.IO.Directory.CreateDirectory(DirectoryPath);
            string currentExe = Assembly.GetExecutingAssembly().Location;
            if (!String.Equals(Path.GetFullPath(currentExe), Path.GetFullPath(Launcher), StringComparison.OrdinalIgnoreCase))
            {
                byte[] current = File.ReadAllBytes(currentExe);
                if (!File.Exists(Launcher) || !Engine.SameBytes(Launcher, current))
                {
                    string temporary = Launcher + "." + Guid.NewGuid().ToString("N") + ".new";
                    try
                    {
                        using (FileStream output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                            output.Write(current, 0, current.Length);
                        if (File.Exists(Launcher)) File.Replace(temporary, Launcher, null);
                        else File.Move(temporary, Launcher);
                    }
                    finally { if (File.Exists(temporary)) File.Delete(temporary); }
                }
            }
            AtomicText(ProfilePath, BootstrapCore.RenderProfile(Payload.Profile, Account));
            AtomicText(TransportPath, BootstrapCore.RenderTransport(Payload.Transport, TransportAccount));
            File.WriteAllBytes(ServerCertPath, BootstrapCore.ServerCertificate(Payload.Profile));
            AtomicText(Path.Combine(DirectoryPath, "public-config.json"), Payload.PublicJson);
            File.WriteAllBytes(Path.Combine(DirectoryPath, "company-ca.cer"), Payload.Files["company-ca.cer"]);
            if (State == null) State = new InstallState {
                AccountName = Account, OwnerSid = Sid, CaSha256 = BootstrapCore.ExpectedCaSha256
            };
            State.TransportAccountName = TransportAccount;
            SaveState();
        }

        internal static bool HasCa()
        {
            using (X509Store store = new X509Store(StoreName.Root, StoreLocation.CurrentUser))
            {
                store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
                foreach (X509Certificate2 certificate in store.Certificates)
                    if (CaMatches(certificate)) return true;
            }
            return false;
        }

        private static bool CaMatches(X509Certificate2 certificate)
        {
            using (SHA256 sha = SHA256.Create())
                return BootstrapCore.Hex(sha.ComputeHash(certificate.RawData)) == BootstrapCore.ExpectedCaSha256;
        }

        private void EnsureCa()
        {
            using (X509Store store = new X509Store(StoreName.Root, StoreLocation.CurrentUser))
            {
                store.Open(OpenFlags.ReadWrite);
                foreach (X509Certificate2 certificate in store.Certificates)
                    if (CaMatches(certificate)) return;
                store.Add(Payload.Ca);
                State.CaAdded = true;
                try { SaveState(); }
                catch
                {
                    store.Remove(Payload.Ca);
                    State.CaAdded = false;
                    throw;
                }
            }
        }

        internal string Prepare(bool connect, bool allowElevation, Action<string> progress)
        {
            try { return PrepareCore(connect, allowElevation, progress); }
            catch
            {
                if (connect && State != null)
                {
                    try { Disconnect(); } catch (Exception cleanup) { throw new AppProblem("cleanup_failed", "连接未完成，且未能确认断开：" + Program.Explain(cleanup).Message); }
                }
                throw;
            }
        }

        private string PrepareCore(bool connect, bool allowElevation, Action<string> progress)
        {
            Payload.RequireActive();
            CheckCancelled();
            progress("正在准备网络组件，请稍候…");
            Engine engine = Engine.Ensure(Payload, allowElevation);
            CheckCancelled();
            bool exists = engine.AccountExists(Account);
            if (exists && (State == null || !State.AccountOwned))
                throw new AppProblem("account_conflict", "发现同名连接，应用没有修改它。请联系管理员确认。");
            bool transportExists = engine.AccountExists(TransportAccount);
            if (transportExists && (State == null || !State.TransportOwned))
                throw new AppProblem("account_conflict", "发现同名连接，请联系管理员确认。");
            progress("正在保存个人配置…");
            SaveFiles();
            if (BootstrapCore.NeedsCompanyCa(Payload.Gpt)) EnsureCa();
            if (connect) CreateShortcuts();
            if (!transportExists)
            {
                // Persist intent before import: a timeout or interrupted save must remain retryable.
                State.TransportOwned = true;
                SaveState();
                Import(engine, TransportPath, TransportAccount);
            }
            if (!exists)
            {
                State.AccountOwned = true;
                SaveState();
                Import(engine, ProfilePath, Account);
                State.ConfigurationVersion = 11;
                SaveState();
            }
            else if (State.ConfigurationVersion < 11)
            {
                DisconnectOwned(engine, Account);
                RequireCommand(engine, "AccountSet " + Processes.Quote(Account) + " /SERVER:10.253.60.1/tcp:443 /HUB:OFFICE_TRIAL");
                RequireCommand(engine, "AccountServerCertSet " + Processes.Quote(Account) + " /LOADCERT:" + Processes.Quote(ServerCertPath));
                RequireCommand(engine, "AccountServerCertEnable " + Processes.Quote(Account));
                RequireCommand(engine, "AccountNicSet " + Processes.Quote(Account) + " /NICNAME:VPN");
                State.ConfigurationVersion = 11;
                SaveState();
            }
            if (!connect) return "个人配置已准备完成，尚未发起连接。";
            try
            {
                BootstrapCore.ConnectLayers(delegate {
                    progress("正在连接公司网络，请稍候…");
                    CheckCancelled(); Connect(engine, TransportAccount);
                }, delegate {
                    return WaitUntil(delegate {
                        bool established = IsEstablished(engine, TransportAccount);
                        bool route = established && HasAdapterRoute("10.253.60.1", true);
                        return BootstrapCore.TransportReady(established, route, route && TcpReady("10.253.60.1", 443));
                    }, 60);
                }, delegate {
                    progress("请在登录窗口输入管理员分配的个人账号…");
                    // Do not reimport: preserve the employee's saved identity and password.
                    // The resident official helper owns the personal credential dialog.
                    // Profiles are already imported; the separate manager window is unnecessary.
                    engine.EnsureUiHelper();
                    CheckCancelled(); Connect(engine, Account);
                }, delegate {
                    return WaitUntil(delegate { return IsEstablished(engine, Account) && HasInnerRoute(); }, 180);
                });
            }
            catch
            {
                throw new AppProblem("connection_incomplete", "连接未完成或登录已取消。正在检查并回收连接，请重新连接并完成个人账号登录。");
            }
            return "公司网络已连接，可以打开 GPT。";
        }

        private static void Import(Engine engine, string path, string account)
        {
            RequireCommand(engine, "AccountImport " + Processes.Quote(path));
            if (!engine.AccountExists(account)) throw new AppProblem("profile_not_found", "连接配置尚未完成，请重试。");
        }

        private static void RequireCommand(Engine engine, string command)
        {
            if (engine.Command(command, 15000).ExitCode != 0)
                throw new AppProblem("profile_update_failed", "连接配置未能准备完成，请重试或联系管理员。");
        }

        private static void Connect(Engine engine, string account)
        {
            int code = engine.Command("AccountConnect " + Processes.Quote(account), 15000).ExitCode;
            if (code != 0 && code != 35) throw new AppProblem("connect_failed", "未能发起连接，请重试。");
        }

        internal static bool IsEstablished(Engine engine, string account)
        {
            CommandResult result = engine.Command("AccountStatusGet " + Processes.Quote(account), 10000);
            return BootstrapCore.Established(result.ExitCode, result.Output);
        }

        private bool WaitUntil(Func<bool> condition, int seconds)
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(seconds);
            do { CheckCancelled(); if (condition()) { CheckCancelled(); return true; } Thread.Sleep(750); } while (DateTime.UtcNow < deadline);
            return false;
        }

        private static bool TcpReady(string host, int port)
        {
            try
            {
                using (TcpClient probe = new TcpClient(AddressFamily.InterNetwork))
                {
                    IAsyncResult pending = probe.BeginConnect(host, port, null, null);
                    using (WaitHandle completed = pending.AsyncWaitHandle)
                    {
                        if (!completed.WaitOne(700)) return false;
                        probe.EndConnect(pending);
                        return true;
                    }
                }
            }
            catch (SocketException) { return false; }
        }

        [DllImport("iphlpapi.dll", SetLastError = true)]
        private static extern uint GetBestInterface(uint destination, out uint index);

        internal static bool HasInnerRoute()
        {
            return HasAdapterRoute("192.168.1.29", false);
        }

        private static bool HasAdapterRoute(string destination, bool transport)
        {
            uint best;
            if (GetBestInterface(BitConverter.ToUInt32(IPAddress.Parse(destination).GetAddressBytes(), 0), out best) != 0) return false;
            foreach (NetworkInterface nic in NetworkInterface.GetAllNetworkInterfaces())
            {
                bool expectedAdapter = transport ? Regex.IsMatch(nic.Description,
                    @"\AVPN Client Adapter - VPN2(?: #[1-9][0-9]*)?\z", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant) : BootstrapCore.IsInnerAdapterDescription(nic.Description);
                if (nic.OperationalStatus != OperationalStatus.Up ||
                    !expectedAdapter) continue;
                IPInterfaceProperties properties = nic.GetIPProperties();
                IPv4InterfaceProperties ipv4 = properties.GetIPv4Properties();
                if (ipv4 == null || ipv4.Index != best) continue;
                foreach (UnicastIPAddressInformation address in properties.UnicastAddresses)
                    if (address.Address.AddressFamily == AddressFamily.InterNetwork &&
                        address.DuplicateAddressDetectionState == DuplicateAddressDetectionState.Preferred &&
                        address.Address.ToString().StartsWith(transport ? "10.253.60." : "10.253.61.", StringComparison.Ordinal)) return true;
            }
            return false;
        }

        private static void DisconnectOwned(Engine engine, string account)
        {
            int code = engine.Command("AccountDisconnect " + Processes.Quote(account), 10000).ExitCode;
            if (code != 0 && code != 36 && code != 37)
                throw new AppProblem("disconnect_failed", "未能确认连接已断开，请在公司网络窗口检查。");
        }

        internal ConnectionSnapshot Snapshot()
        {
            ReloadState();
            ConnectionSnapshot snapshot = new ConnectionSnapshot();
            if (State == null || (!State.AccountOwned && !State.TransportOwned)) return snapshot;
            Engine engine = Engine.Find();
            if (engine == null || Engine.ServiceStatus() == "Stopped" || Engine.ServiceStatus() == "NotInstalled") return snapshot;
            engine.RequireRpc();
            snapshot.Outer = State.TransportOwned && SessionActive(engine, TransportAccount);
            snapshot.Inner = State.AccountOwned && SessionActive(engine, Account);
            snapshot.Route = snapshot.Inner && HasInnerRoute();
            snapshot.SessionsReady = snapshot.Inner && snapshot.Outer && IsEstablished(engine, Account) && IsEstablished(engine, TransportAccount);
            return snapshot;
        }

        private static bool SessionActive(Engine engine, string account)
        {
            CommandResult result = engine.Command("AccountStatusGet " + Processes.Quote(account), 10000);
            if (result.ExitCode == 36 || result.ExitCode == 37) return false;
            if (result.ExitCode != 0) throw new AppProblem("status_unavailable", "无法读取实际会话，尚未确认断开，请重试。");
            // AccountStatusGet succeeds for connecting/reconnecting sessions too.
            return true;
        }

        internal string Disconnect()
        {
            if (State == null || (!State.AccountOwned && !State.TransportOwned)) return "当前用户尚未配置连接。";
            Engine engine = Engine.Find();
            if (engine == null || Engine.ServiceStatus() != "Running") return "连接已断开。";
            Exception failure = null;
            try { if (State.AccountOwned) DisconnectOwned(engine, Account); } catch (Exception e) { failure = e; }
            try { if (State.TransportOwned) DisconnectOwned(engine, TransportAccount); } catch (Exception e) { failure = e; }
            if (failure != null) throw failure;
            if (Snapshot().Kind != "disconnected") throw new AppProblem("disconnect_unconfirmed", "尚未确认两层连接均已结束，请重试断开。");
            return "连接已断开。";
        }

        internal string Remove()
        {
            if (State == null) return "没有找到由本应用创建的个人配置。";
            Engine engine = Engine.Find();
            if (State.TransportOwned && engine != null)
            {
                engine.RequireRpc();
                Disconnect();
                int code = engine.Command("AccountDelete " + Processes.Quote(TransportAccount), 10000).ExitCode;
                if (code != 0 && code != 36) throw new AppProblem("remove_account_failed", "个人连接尚未移除，请稍后重试。");
                State.TransportOwned = false;
                SaveState();
            }
            if (State.AccountOwned && engine != null)
            {
                engine.RequireRpc();
                Disconnect();
                int code = engine.Command("AccountDelete " + Processes.Quote(Account), 10000).ExitCode;
                if (code != 0 && code != 36)
                    throw new AppProblem("remove_account_failed", "个人连接尚未移除，请稍后重试。");
                State.AccountOwned = false;
                SaveState();
            }
            RemoveShortcuts();
            if (State.CaAdded)
            {
                using (X509Store store = new X509Store(StoreName.Root, StoreLocation.CurrentUser))
                {
                    store.Open(OpenFlags.ReadWrite);
                    foreach (X509Certificate2 certificate in store.Certificates)
                        if (CaMatches(certificate)) store.Remove(certificate);
                }
                State.CaAdded = false;
                SaveState();
            }
            foreach (string name in new string[] { "profile.vpn", "transport.vpn", "server-pin.cer", "public-config.json", "company-ca.cer", "state.json" })
            {
                string path = Path.Combine(DirectoryPath, name);
                if (File.Exists(path)) File.Delete(path);
            }
            State = null;
            return "本应用的个人连接、快捷方式及新增信任已移除。";
        }

        internal string OpenGpt()
        {
            Payload.RequireActive();
            if (State == null || !State.AccountOwned || !State.TransportOwned || State.ConfigurationVersion < 11 ||
                (BootstrapCore.NeedsCompanyCa(Payload.Gpt) && !HasCa()))
                throw new AppProblem("configure_first", "请先完成“安装并连接”，再打开 GPT。");
            Engine engine = Engine.Find();
            if (engine == null || Engine.ServiceStatus() != "Running" || !IsEstablished(engine, Account) || !HasInnerRoute())
                throw new AppProblem("connect_first", "公司网络尚未连接完成，请先连接后再打开 GPT。");
            ProcessStartInfo start = new ProcessStartInfo(Payload.Gpt.AbsoluteUri) { UseShellExecute = true };
            using (Process process = Process.Start(start)) { }
            return "已打开 GPT。";
        }

        private void CreateShortcuts()
        {
            UpdateShortcuts(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Launcher, DirectoryPath, State != null && State.OwnerSid == Sid, false);
        }

        private void RemoveShortcuts()
        {
            UpdateShortcuts(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Launcher, DirectoryPath, State != null && State.OwnerSid == Sid, true);
        }

        internal static void UpdateShortcuts(string desktop, string launcher, string directory, bool installationOwned, bool remove)
        {
            if (!installationOwned) throw new AppProblem("shortcut_ownership_unknown", "无法确认安装归属，未修改桌面入口。");
            Type type = Type.GetTypeFromProgID("WScript.Shell");
            if (type == null) throw new AppProblem("shortcuts_unavailable", "系统暂时无法创建快捷方式，可直接打开本应用使用。");
            string[] names = { "公司网络.lnk", "公司网络-连接.lnk", "公司网络-断开.lnk", "公司网络-GPT.lnk" };
            string[] args = { "--ui", "--connect", "--disconnect", "--gpt" };
            bool conflict = false;
            object shell = Activator.CreateInstance(type);
            try
            {
                // Preflight the unified entry before deleting any legacy entry.
                for (int i = 0; i < names.Length; i++)
                {
                    string path = Path.Combine(desktop, names[i]);
                    object shortcut = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
                    try
                    {
                        Type t = shortcut.GetType();
                        bool exists = File.Exists(path);
                        bool owned = !exists ||
                            String.Equals((string)t.InvokeMember("TargetPath", BindingFlags.GetProperty, null, shortcut, null), launcher, StringComparison.OrdinalIgnoreCase) &&
                            String.Equals(((string)t.InvokeMember("Arguments", BindingFlags.GetProperty, null, shortcut, null)).Trim(), args[i], StringComparison.Ordinal) &&
                            String.Equals((string)t.InvokeMember("WorkingDirectory", BindingFlags.GetProperty, null, shortcut, null), directory, StringComparison.OrdinalIgnoreCase);
                        if (!owned) { conflict = true; if(i == 0 && !remove) throw new AppProblem("shortcut_conflict", "桌面“公司网络”入口归属不明，已保留，请联系管理员确认。"); continue; }
                        if(remove || i > 0) { if(exists) File.Delete(path); continue; }
                        t.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { launcher });
                        t.InvokeMember("Arguments", BindingFlags.SetProperty, null, shortcut, new object[] { "--ui" });
                        t.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { directory });
                        t.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { launcher + ",0" });
                        t.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { "公司网络：连接、断开与 GPT" });
                        t.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
                    }
                    finally { Marshal.FinalReleaseComObject(shortcut); }
                }
            }
            finally { Marshal.FinalReleaseComObject(shell); }
            if(conflict && !remove) throw new AppProblem("shortcut_conflict", "已创建统一入口；归属不明的同名旧入口已保留，请联系管理员确认。");
        }
    }
}
