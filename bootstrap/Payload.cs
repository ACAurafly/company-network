using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Web.Script.Serialization;

namespace CompanyNetwork
{
    internal sealed class AppProblem : Exception
    {
        internal readonly string Code;
        internal readonly int NativeError;
        internal AppProblem(string code, string message) : this(code, message, -1) { }
        internal AppProblem(string code, string message, int nativeError) : base(message)
        {
            Code = code;
            NativeError = nativeError;
        }
    }

    internal sealed class AppPayload
    {
        internal const string ResourceName = "company.payload.zip";
        internal readonly Dictionary<string, byte[]> Files = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        internal string Profile;
        internal string Transport;
        internal string PublicJson;
        internal string Server;
        internal string Hub;
        internal string AccountPrefix;
        internal DateTimeOffset ExpiresAt;
        internal Uri Gpt;
        internal X509Certificate2 Ca;

        internal static AppPayload Read()
        {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(ResourceName))
            {
                if (stream == null) throw new AppProblem("payload_missing", "安装包尚未完成，请向管理员取得完整安装包。");
                return Read(stream);
            }
        }

        internal static AppPayload Read(Stream stream)
        {
            AppPayload payload = new AppPayload();
            long total = 0;
            using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read, true))
            {
                HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    string name = BootstrapCore.EntryName(entry.FullName);
                    if (!seen.Add(name)) throw new InvalidDataException("Duplicate ZIP entry.");
                    if (name == "engine/") continue;
                    if (entry.Length < 0 || entry.Length > 128L * 1024 * 1024 ||
                        (total += entry.Length) > 256L * 1024 * 1024)
                        throw new InvalidDataException("Payload is too large.");
                    using (Stream input = entry.Open())
                    using (MemoryStream output = new MemoryStream())
                    {
                        byte[] buffer = new byte[81920];
                        int read;
                        while ((read = input.Read(buffer, 0, buffer.Length)) != 0)
                        {
                            if (output.Length + read > entry.Length) throw new InvalidDataException("ZIP size mismatch.");
                            output.Write(buffer, 0, read);
                        }
                        if (output.Length != entry.Length) throw new InvalidDataException("ZIP size mismatch.");
                        payload.Files.Add(name, output.ToArray());
                    }
                }
            }
            foreach (string file in BootstrapCore.EngineFiles)
                payload.Required("engine/" + file);
            payload.Profile = Text(payload.Required("profile.vpn"));
            payload.Transport = Text(payload.Required("transport.vpn"));
            payload.PublicJson = Text(payload.Required("public-config.json"));
            byte[] caBytes = payload.Required("company-ca.cer");
            BootstrapCore.ValidateCaHash(caBytes);
            payload.Ca = new X509Certificate2(caBytes);
            bool isCa = false;
            foreach (X509Extension extension in payload.Ca.Extensions)
            {
                if (extension.Oid.Value == "2.5.29.19")
                    isCa = new X509BasicConstraintsExtension(extension, extension.Critical).CertificateAuthority;
            }
            if (!isCa) throw new InvalidDataException("Pinned certificate is not a CA.");
            JavaScriptSerializer json = Json();
            Dictionary<string, object> config = json.Deserialize<Dictionary<string, object>>(payload.PublicJson);
            if (config == null || config.Count != 5) throw new InvalidDataException("Invalid public configuration.");
            payload.Server = Value(config, "server");
            payload.Hub = Value(config, "hub");
            payload.AccountPrefix = Value(config, "accountPrefix");
            payload.Gpt = BootstrapCore.GptUri(Value(config, "gptUrl"));
            if (!DateTimeOffset.TryParse(Value(config, "expiresAt"), CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out payload.ExpiresAt))
                throw new InvalidDataException("Invalid expiration date.");
            // Validate the template before any service, trust-store or filesystem change.
            BootstrapCore.RenderProfile(payload.Profile, BootstrapCore.AccountName(payload.AccountPrefix, "S-1-5-21-0"));
            BootstrapCore.ValidateEndpoint(payload.Profile, false);
            BootstrapCore.RenderTransport(payload.Transport, BootstrapCore.AccountName("CompanyTransport", "S-1-5-21-0"));
            return payload;
        }

        private byte[] Required(string name)
        {
            byte[] value;
            if (!Files.TryGetValue(name, out value) || value.Length == 0) throw new InvalidDataException("Missing payload file.");
            return value;
        }

        private static string Text(byte[] value)
        {
            return new UTF8Encoding(false, true).GetString(value).TrimStart('\uFEFF');
        }

        private static string Value(Dictionary<string, object> config, string key)
        {
            object value;
            if (!config.TryGetValue(key, out value) || !(value is string) ||
                String.IsNullOrWhiteSpace((string)value) || ((string)value).Length > 2048 ||
                ((string)value).IndexOfAny(new char[] { '\r', '\n', '\0' }) >= 0)
                throw new InvalidDataException("Invalid public configuration field.");
            return (string)value;
        }

        internal void RequireActive()
        {
            // Legacy packages still contain expiresAt, but account access is
            // controlled by the administrator on the VPN server, not a local date.
        }

        internal static JavaScriptSerializer Json()
        {
            return new JavaScriptSerializer { MaxJsonLength = 2 * 1024 * 1024, RecursionLimit = 12 };
        }
    }
}
