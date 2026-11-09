using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace CompanyNetwork
{
    internal static class BootstrapCore
    {
        internal const string ExpectedCaSha256 = "8A661C390E4D7EFFB7D5498535FFA6AF4B374C7A7E252B2339C50249387BE9B6";
        internal static readonly string[] EngineFiles = new string[] {
            "vpnclient_x64.exe", "vpncmd_x64.exe", "vpncmgr_x64.exe", "vpninstall.exe",
            "hamcore.se2", "lang.config", "LICENSE.txt"
        };

        internal static string AccountName(string prefix, string sid)
        {
            if (prefix == null || !Regex.IsMatch(prefix, @"\A[A-Za-z0-9_-]{1,40}\z") ||
                sid == null || !Regex.IsMatch(sid, @"\AS-\d+(?:-\d+)+\z"))
                throw new InvalidDataException("Invalid account identity.");
            byte[] hash;
            using (SHA256 sha = SHA256.Create()) hash = sha.ComputeHash(Encoding.UTF8.GetBytes(sid));
            return prefix + "-" + Hex(hash).Substring(0, 16);
        }

        internal static string EntryName(string name)
        {
            if (name == "engine/") return name;
            foreach (string item in new string[] { "profile.vpn", "transport.vpn", "company-ca.cer", "public-config.json" })
                if (String.Equals(name, item, StringComparison.Ordinal)) return item;
            foreach (string item in EngineFiles)
                if (String.Equals(name, "engine/" + item, StringComparison.Ordinal)) return "engine/" + item;
            throw new InvalidDataException("Unexpected ZIP entry.");
        }

        private static Match SingleField(string text, string pattern)
        {
            MatchCollection matches = Regex.Matches(text, pattern, RegexOptions.Multiline);
            if (matches.Count != 1) throw new InvalidDataException("Missing or duplicate profile field.");
            return matches[0];
        }

        internal static string RenderProfile(string text, string account)
        {
            if (text == null || text.Length > 1024 * 1024 || account == null ||
                !Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,100}\z"))
                throw new InvalidDataException("Invalid profile.");
            Match name = SingleField(text, @"^[ \t]*string[ \t]+AccountName[ \t]+([^\r\n]*)\r?$");
            if (name.Groups[1].Value.Trim() != "COMPANY_ACCOUNT") throw new InvalidDataException("Missing account placeholder.");
            Match user = SingleField(text, @"^[ \t]*string[ \t]+Username(?:[ \t]+([^\r\n]*))?\r?$");
            if (!EmptyStringValue(user.Groups[1].Value)) throw new InvalidDataException("Profile contains a username.");
            Match auth = SingleField(text, @"^[ \t]*uint[ \t]+AuthType[ \t]+([^\r\n]*)\r?$");
            if (auth.Groups[1].Value.Trim() != "1") throw new InvalidDataException("Only standard password authentication is supported.");
            Match password = SingleField(text, @"^[ \t]*byte[ \t]+HashedPassword[ \t]+([^\r\n]*)\r?$");
            byte[] passwordBytes;
            try { passwordBytes = Convert.FromBase64String(password.Groups[1].Value.Trim()); }
            catch (FormatException) { throw new InvalidDataException("Invalid password field."); }
            if (passwordBytes.Length != 20) throw new InvalidDataException("Invalid password length.");
            foreach (byte item in passwordBytes)
                if (item != 0) throw new InvalidDataException("Profile contains a password hash.");
            if (!Regex.IsMatch(text, @"^[ \t]*bool[ \t]+CheckServerCert[ \t]+true[ \t]*\r?$", RegexOptions.Multiline) ||
                !Regex.IsMatch(text, @"^[ \t]*byte[ \t]+ServerCert[ \t]+[^\s]+[ \t]*\r?$", RegexOptions.Multiline))
                throw new InvalidDataException("Pinned server certificate is required.");
            Match device = SingleField(text, @"^[ \t]*string[ \t]+DeviceName[ \t]+([^\r\n]*)\r?$");
            if (device.Groups[1].Value.Trim() != "VPN") throw new InvalidDataException("Expected the VPN virtual adapter.");
            MatchCollection credentials = Regex.Matches(text,
                @"^[ \t]*(?:byte|string)[ \t]+(?:ClientKey|EncryptedPassword|PlainPassword|Password|ProxyUsername|ProxyPassword)(?:[ \t]+([^\r\n]*))?\r?$", RegexOptions.Multiline);
            foreach (Match credential in credentials)
                if (!EmptyStringValue(credential.Groups[1].Value)) throw new InvalidDataException("Unexpected credential material.");
            return text.Substring(0, name.Groups[1].Index) + account + text.Substring(name.Groups[1].Index + name.Groups[1].Length);
        }

        private static bool EmptyStringValue(string value)
        {
            string trimmed = value.Trim();
            return trimmed.Length == 0 || trimmed == "$";
        }

        internal static string Field(string text, string type, string name)
        {
            return SingleField(text, @"^[ \t]*" + type + @"[ \t]+" + name + @"[ \t]+([^\r\n]*)\r?$").Groups[1].Value.Trim();
        }

        internal static byte[] ServerCertificate(string text)
        {
            byte[] bytes = Convert.FromBase64String(Field(text, "byte", "ServerCert"));
            using (System.Security.Cryptography.X509Certificates.X509Certificate2 certificate =
                new System.Security.Cryptography.X509Certificates.X509Certificate2(bytes))
                return certificate.Export(System.Security.Cryptography.X509Certificates.X509ContentType.Cert);
        }

        internal static void ValidateEndpoint(string text, bool transport)
        {
            if (Field(text, "string", "Hostname") != (transport ? "office-trial-2dd76438.vpnazure.net/tcp" : "10.253.60.1/tcp") ||
                Field(text, "uint", "Port") != "443" || Field(text, "string", "HubName") != (transport ? "OFFICE_TRANSPORT" : "OFFICE_TRIAL") ||
                Field(text, "bool", "UseEncrypt") != "true" || Field(text, "bool", "CheckServerCert") != "true" ||
                Field(text, "bool", "NoUdpAcceleration") != "true")
                throw new InvalidDataException("Invalid protected endpoint.");
            ServerCertificate(text);
        }

        internal static string RenderTransport(string text, string account)
        {
            // Reuse credential validation after translating only the public bootstrap identity.
            if (Field(text, "string", "AccountName") != "COMPANY_TRANSPORT" ||
                Field(text, "string", "Username") != "transport" || Field(text, "uint", "AuthType") != "0" ||
                Field(text, "string", "DeviceName") != "VPN2")
                throw new InvalidDataException("Invalid public transport identity.");
            ValidateEndpoint(text, true);
            string check = Regex.Replace(text, @"(?m)(^[ \t]*string[ \t]+AccountName[ \t]+)COMPANY_TRANSPORT\r?$", "$1COMPANY_ACCOUNT");
            check = Regex.Replace(check, @"(?m)(^[ \t]*string[ \t]+Username[ \t]+)transport\r?$", "$1$");
            check = Regex.Replace(check, @"(?m)(^[ \t]*uint[ \t]+AuthType[ \t]+)0\r?$", "${1}1");
            check = Regex.Replace(check, @"(?m)(^[ \t]*string[ \t]+DeviceName[ \t]+)VPN2\r?$", "$1VPN");
            if (!Regex.IsMatch(check, @"(?m)^[ \t]*byte[ \t]+HashedPassword\b"))
                check += "\nbyte HashedPassword AAAAAAAAAAAAAAAAAAAAAAAAAAA=\n";
            RenderProfile(check, account);
            return text.Replace("COMPANY_TRANSPORT", account);
        }

        internal static bool IsInnerAdapterDescription(string description)
        {
            return description != null && Regex.IsMatch(description,
                @"\AVPN Client Adapter - VPN(?: #[1-9][0-9]*)?\z", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        }

        internal static bool Established(int exitCode, string status)
        {
            return exitCode == 0 && status != null && Regex.IsMatch(status, @"\bSID-[A-Za-z0-9_-]+", RegexOptions.IgnoreCase);
        }

        internal static bool TransportReady(bool established, bool assignedRoute, bool reachable)
        {
            return established && assignedRoute && reachable;
        }

        internal static void ConnectLayers(Action startOuter, Func<bool> outerReady, Action startInner, Func<bool> innerReady)
        {
            startOuter();
            if (!outerReady()) throw new InvalidOperationException("transport_unavailable");
            startInner();
            if (!innerReady()) throw new InvalidOperationException("employee_connection_unavailable");
        }

        internal static Uri GptUri(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri) ||
                !String.IsNullOrEmpty(uri.UserInfo) || String.IsNullOrEmpty(uri.Host))
                throw new InvalidDataException("GPT URL must be HTTPS and contain no credentials.");
            if (uri.Scheme != Uri.UriSchemeHttps && !(uri.Scheme == Uri.UriSchemeHttp &&
                uri.Host == "192.168.1.29" && uri.Port == 8080 && (uri.AbsolutePath == "/" || uri.AbsolutePath == "/v1") &&
                uri.Query.Length == 0 && uri.Fragment.Length == 0))
                throw new InvalidDataException("GPT URL is not an approved target.");
            return uri;
        }

        internal static bool NeedsCompanyCa(Uri gpt)
        {
            return gpt != null && gpt.Scheme == Uri.UriSchemeHttps;
        }

        internal static void ValidateCaHash(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0 || bytes.Length > 65536) throw new InvalidDataException("Invalid CA file.");
            string hash;
            using (SHA256 sha = SHA256.Create()) hash = Hex(sha.ComputeHash(bytes));
            if (!String.Equals(hash, ExpectedCaSha256, StringComparison.Ordinal))
                throw new InvalidDataException("CA fingerprint mismatch.");
        }

        internal static string Hex(byte[] bytes)
        {
            return BitConverter.ToString(bytes).Replace("-", "");
        }
    }
}
