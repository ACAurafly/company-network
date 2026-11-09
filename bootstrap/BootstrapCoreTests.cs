using System;
using System.IO;
using System.Text;
using CompanyNetwork;

internal static class BootstrapCoreTests
{
    private static int passed;
    private static int failed;
    private const string PublicTestPin = "MIIFAzCCA+ugAwIBAgISBeTJ/nAYCFTtV6eb9sfTYnbOMA0GCSqGSIb3DQEBCwUAMDMxCzAJBgNVBAYTAlVTMRYwFAYDVQQKEw1MZXQncyBFbmNyeXB0MQwwCgYDVQQDEwNZUjEwHhcNMjYxMDI3MTgxNDQzWhcNMjcwMTI1MTgxNDQyWjAXMRUwEwYDVQQDEwx2cG5henVyZS5uZXQwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCTgSkZzs12uYDbeMPt/Vp1bZZhfk43p+RQl8hjtiGZlHhtY5qaz72LEtLWpxs6NsFHDE+TMZNdp0EYFWOObX/G31MFMfe+3GkaaCBzXA7MEvAhwPjAJMEeeIj7e3wvFUMO5wlB63AUA0l31MnuJSeH3bVSrq3qbN7Z+kmwAWBb2Di/3XHLJGyPuMuvWxp0JCBKQvuyvwaYNfTcHrEs55uuQDH41oqhAIbwZ0Ch4+L0DBreGQvJIJqVKnNWOgP7adV5jMIZQ5BzVN/1v5dBmCTlutsj4qkZDSUSAgxIjp+uKgICL/ciPHTYICMG1vkTNT2/W0bverifnGJ7hE4eEfd/AgMBAAGjggIrMIICJzAOBgNVHQ8BAf8EBAMCBaAwEwYDVR0lBAwwCgYIKwYBBQUHAwEwDAYDVR0TAQH/BAIwADAdBgNVHQ4EFgQUb0oJg5Ec57v3uUK72YLTAQAN+kYwHwYDVR0jBBgwFoAUHy81vkYUgs1Asa55LFV4+vfUaPswMwYIKwYBBQUHAQEEJzAlMCMGCCsGAQUFBzAChhdodHRwOi8veXIxLmkubGVuY3Iub3JnLzAnBgNVHREEIDAegg4qLnZwbmF6dXJlLm5ldIIMdnBuYXp1cmUubmV0MBMGA1UdIAQMMAowCAYGZ4EMAQIBMC4GA1UdHwQnMCUwI6AhoB+GHWh0dHA6Ly95cjEuYy5sZW5jci5vcmcvNzkuY3JsMIIBDQYKKwYBBAHWeQIEAgSB/gSB+wD5AHYATGPcmOWcHauI9h6KPd6uj6tEozd7X5uUw/uhnPzBviYAAAGhfsfqywAABAMARzBFAiEAy7gWb7S7hnqjgtm6w30IO7hqMECQo9qG0XtJZUK30vACIAUSpLiZCbIqy+4S9Z/KH5ruIY5ZOOSF5PbS2/GgoC+NAH8AooEAGHNOF24dR+CVQPOBulRml81jqENQcW64CU7a8Q0AAAGhfsftaAAIAAAFAC/KnyAEAwBIMEYCIQDuibrKNSyJAgVhOfh8JBUz9bEPAV49brrl6Vle2g8qEAIhAIFKL/SOkYzpbsmlH+JSzQWsZjpjHsEGPJp8a/E0NM6OMA0GCSqGSIb3DQEBCwUAA4IBAQBBWs3uC0hqDqCI8vyW/Iho0n1g0P8ihMXc6Q8RdAiRKJn7gI/PPTsf7/zrxGNolOq8vjbQfYwOA9vnsl6/NH9PGMolaxQZkT4hGkpvelkgT+HpSGzLwtiXGDM1nqKmb8sG/uJpyKw5pTfnE+GYuNIQY7IyuFCSpD/zViKOa1Wn9rss5d5bzA3bPeDJ0J1fTV7CowyQ0NO4QWFxLYuCl1dS2BEQknO4TF6WhHO0nsqAeeMMndqU8j8lXmmBr365eTD47jfur1GXY+U/IcD14dZjfyRm62ScDpsKoEnUN5q9cQvc7Cf1GiTZIKIHDqQu+zAR95VxW6zodP6qn46fI80D";
    private const string Profile = "declare root\r\n{\r\n declare ClientOption\r\n {\r\n  string AccountName COMPANY_ACCOUNT\r\n  string DeviceName VPN\r\n  bool NoUdpAcceleration true\r\n }\r\n declare ClientAuth\r\n {\r\n  uint AuthType 1\r\n  string Username\r\n  byte HashedPassword AAAAAAAAAAAAAAAAAAAAAAAAAAA=\r\n }\r\n bool CheckServerCert true\r\n byte ServerCert cHVibGljLWNlcnQ=\r\n}\r\n";

    private static void Check(string name, Action body)
    {
        try { body(); passed++; Console.WriteLine("PASS " + name); }
        catch (Exception e) { failed++; Console.WriteLine("FAIL " + name + ": " + e.GetType().Name); }
    }
    private static void Equal(object expected, object actual)
    {
        if (!Object.Equals(expected, actual)) throw new Exception("Assertion failed");
    }
    private static void Reject(Action body)
    {
        try { body(); } catch (InvalidDataException) { return; }
        throw new Exception("Expected validation rejection");
    }
    private static int Main()
    {
        Check("account is stable per SID and differs between users", delegate {
            string a = BootstrapCore.AccountName("Trial", "S-1-5-21-111");
            Equal(a, BootstrapCore.AccountName("Trial", "S-1-5-21-111"));
            if (a == BootstrapCore.AccountName("Trial", "S-1-5-21-222")) throw new Exception();
            if (!a.StartsWith("Trial-", StringComparison.Ordinal)) throw new Exception();
        });
        Check("account prefix cannot inject CLI arguments", delegate {
            Reject(delegate { BootstrapCore.AccountName("x\" /CMD AccountDelete", "S-1"); });
        });
        Check("ZIP accepts the declared layout", delegate {
            Equal("engine/vpnclient_x64.exe", BootstrapCore.EntryName("engine/vpnclient_x64.exe"));
            Equal("profile.vpn", BootstrapCore.EntryName("profile.vpn"));
            Equal("company-ca.cer", BootstrapCore.EntryName("company-ca.cer"));
        });
        Check("ZIP traversal and undeclared executables are rejected", delegate {
            foreach (string value in new string[] { "../profile.vpn", "engine/../../bad.exe", "C:/bad.exe", "engine\\..\\bad.exe", "engine/evil.exe", "engine/vpncmd_x64.exe:stream" })
                Reject(delegate { BootstrapCore.EntryName(value); });
        });
        Check("profile changes only the placeholder", delegate {
            string rendered = BootstrapCore.RenderProfile(Profile, "Trial-1234");
            Equal(Profile.Replace("COMPANY_ACCOUNT", "Trial-1234"), rendered);
            if (!rendered.Contains("byte ServerCert cHVibGljLWNlcnQ=")) throw new Exception();
        });
        Check("official dollar empty markers remain unchanged", delegate {
            string canonical = Profile.Replace("string Username\r", "string Username $\r")
                .Replace("  string DeviceName VPN\r", "  string DeviceName VPN\r\n  string ProxyUsername $\r");
            Equal(canonical.Replace("COMPANY_ACCOUNT", "Trial-1234"), BootstrapCore.RenderProfile(canonical, "Trial-1234"));
        });
        Check("profile containing an employee username is rejected", delegate {
            Reject(delegate { BootstrapCore.RenderProfile(Profile.Replace("string Username\r", "string Username somebody\r"), "Trial-1234"); });
        });
        Check("profile containing a password hash is rejected", delegate {
            Reject(delegate { BootstrapCore.RenderProfile(Profile.Replace("AAAAAAAAAAAAAAAAAAAAAAAAAAA=", "AQAAAAAAAAAAAAAAAAAAAAAAAAA="), "Trial-1234"); });
        });
        Check("profile cannot omit server certificate verification", delegate {
            Reject(delegate { BootstrapCore.RenderProfile(Profile.Replace("bool CheckServerCert true", "bool CheckServerCert false"), "Trial-1234"); });
        });
        Check("only HTTPS GPT links without embedded credentials are accepted", delegate {
            Equal("https", BootstrapCore.GptUri("https://10.253.61.1:8443/").Scheme);
            Reject(delegate { BootstrapCore.GptUri("http://10.253.61.1:8080/"); });
            Reject(delegate { BootstrapCore.GptUri("https://user:password@example.invalid/"); });
        });
        Check("CA fingerprint mismatch fails closed", delegate {
            Reject(delegate { BootstrapCore.ValidateCaHash(Encoding.UTF8.GetBytes("not the pinned CA")); });
        });
        Check("only the fixed internal HTTP GPT target is accepted", delegate {
            Equal("http", BootstrapCore.GptUri("http://192.168.1.29:8080/").Scheme);
            Equal("/v1", BootstrapCore.GptUri("http://192.168.1.29:8080/v1").AbsolutePath);
            foreach (string url in new string[] { "http://192.168.1.29/", "http://192.168.1.29:8080/other", "http://user@192.168.1.29:8080/", "http://192.168.1.30:8080/", "http://192.168.1.29:8080/?x=1" })
                Reject(delegate { BootstrapCore.GptUri(url); });
        });
        Check("company root trust is needed only for HTTPS GPT", delegate {
            Equal(false, BootstrapCore.NeedsCompanyCa(BootstrapCore.GptUri("http://192.168.1.29:8080/")));
            Equal(true, BootstrapCore.NeedsCompanyCa(BootstrapCore.GptUri("https://10.253.61.1:8443/")));
        });
        Check("transport rejects employee identity and unsafe authentication before certificate handling", delegate {
            string template = Profile.Replace("COMPANY_ACCOUNT", "COMPANY_TRANSPORT").Replace("DeviceName VPN", "DeviceName VPN2")
                .Replace("string Username\r", "string Username transport\r").Replace("AuthType 1", "AuthType 0");
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("Username transport", "Username employee"), "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("AuthType 0", "AuthType 1"), "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("DeviceName VPN2", "DeviceName Other"), "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("CheckServerCert true", "CheckServerCert false"), "Transport-1234"); });
        });
        Check("established status uses the session name in any language", delegate {
            Equal(true, BootstrapCore.Established(0, "会话名称 | SID-TRANSPORT-17"));
            Equal(false, BootstrapCore.Established(0, "连接状态 | 正在连接"));
            Equal(false, BootstrapCore.Established(1, "SID-STALE-1"));
        });
        Check("transport preserves the public identity and rejects hidden credential material", delegate {
            string template = Profile.Replace("COMPANY_ACCOUNT", "COMPANY_TRANSPORT").Replace("DeviceName VPN", "DeviceName VPN2")
                .Replace("string Username\r", "string Username transport\r").Replace("AuthType 1", "AuthType 0")
                .Replace("cHVibGljLWNlcnQ=", PublicTestPin)
                .Replace(" bool CheckServerCert", " string Hostname office-trial-2dd76438.vpnazure.net/tcp\r\n uint Port 443\r\n string HubName OFFICE_TRANSPORT\r\n bool UseEncrypt true\r\n bool CheckServerCert");
            Equal(template.Replace("COMPANY_TRANSPORT", "Transport-1234"), BootstrapCore.RenderTransport(template, "Transport-1234"));
            Equal(template.Replace("COMPANY_TRANSPORT", "Transport-1234").Replace("  byte HashedPassword AAAAAAAAAAAAAAAAAAAAAAAAAAA=\r\n", ""),
                BootstrapCore.RenderTransport(template.Replace("  byte HashedPassword AAAAAAAAAAAAAAAAAAAAAAAAAAA=\r\n", ""), "Transport-1234"));
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("AAAAAAAAAAAAAAAAAAAAAAAAAAA=", "AQAAAAAAAAAAAAAAAAAAAAAAAAA="), "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template + "string PlainPassword secret\r\n", "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template + "byte EncryptedPassword c2VjcmV0\r\n", "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("NoUdpAcceleration true", "NoUdpAcceleration false"), "Transport-1234"); });
            Reject(delegate { BootstrapCore.RenderTransport(template.Replace("office-trial-2dd76438.vpnazure.net/tcp", "other.invalid"), "Transport-1234"); });
        });
        Check("employee connection starts only after transport is ready", delegate {
            StringBuilder calls = new StringBuilder();
            try {
                BootstrapCore.ConnectLayers(delegate { calls.Append("outer"); }, delegate { return false; }, delegate { calls.Append("inner"); }, delegate { return true; });
                throw new Exception("Missing failure");
            } catch (InvalidOperationException) { }
            Equal("outer", calls.ToString());
            calls.Length = 0;
            BootstrapCore.ConnectLayers(delegate { calls.Append("outer,"); }, delegate { calls.Append("ready,"); return true; }, delegate { calls.Append("inner,"); }, delegate { calls.Append("route"); return true; });
            Equal("outer,ready,inner,route", calls.ToString());
        });
        Check("a reinstalled inner adapter may have a Windows numeric suffix", delegate {
            Equal(true, BootstrapCore.IsInnerAdapterDescription("VPN Client Adapter - VPN"));
            Equal(true, BootstrapCore.IsInnerAdapterDescription("VPN Client Adapter - VPN #2"));
            Equal(false, BootstrapCore.IsInnerAdapterDescription("VPN Client Adapter - VPN2"));
            Equal(false, BootstrapCore.IsInnerAdapterDescription("VPN Client Adapter - VPN2 #2"));
            Equal(false, BootstrapCore.IsInnerAdapterDescription("Ethernet"));
        });
        Check("an unrelated reachable endpoint cannot substitute for the transport DHCP route", delegate {
            Equal(false, BootstrapCore.TransportReady(true, false, true));
            Equal(false, BootstrapCore.TransportReady(false, true, true));
            Equal(false, BootstrapCore.TransportReady(true, true, false));
            Equal(true, BootstrapCore.TransportReady(true, true, true));
        });
        Console.WriteLine("Passed: " + passed + "; failed: " + failed);
        return failed == 0 ? 0 : 1;
    }
}
