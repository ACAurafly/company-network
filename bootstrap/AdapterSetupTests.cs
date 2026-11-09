using System;

namespace CompanyNetwork
{
    internal static class AdapterSetupTests
    {
        private static int Main()
        {
            try
            {
                // Legacy public configs retain their date for package compatibility.
                // Reintroducing a local date gate must fail this regression test.
                foreach (DateTimeOffset legacyDate in new DateTimeOffset[] {
                    DateTimeOffset.MinValue,
                    new DateTimeOffset(2020, 1, 1, 0, 0, 0, TimeSpan.Zero),
                    DateTimeOffset.UtcNow.AddDays(-1)
                })
                    new AppPayload { ExpiresAt = legacyDate }.RequireActive();
                Console.WriteLine("PASS: a past legacy expiration never blocks installation, connection or GPT access");

                bool helperReady = false;
                bool adapterInstalled = false;
                int installations = 0;
                // Vista+ installs a VLan through the UI helper. Model that external
                // boundary: no helper means native ERR_VLAN_INSTALL_ERROR (31).
                Engine.EnsureNic(delegate(string command) {
                    if (command == "NicGetSetting VPN") return adapterInstalled ? 0 : 29;
                    if (command != "NicCreate VPN") throw new Exception("Unexpected command");
                    installations++;
                    if (!helperReady) return 31;
                    adapterInstalled = true;
                    return 0;
                }, delegate { helperReady = true; });
                if (!adapterInstalled || installations != 1) throw new Exception("First installation did not create the adapter");
                Console.WriteLine("PASS: first installation prepares the required helper before creating a missing adapter");

                Engine.EnsureNic(delegate(string command) {
                    if (command != "NicGetSetting VPN") throw new Exception("Existing adapter was modified");
                    return 0;
                }, delegate { throw new Exception("Existing adapter needlessly started a helper"); });
                Console.WriteLine("PASS: an existing adapter is reused without installation");

                bool attempted = false;
                try
                {
                    Engine.EnsureNic(delegate(string command) {
                        if (command == "NicCreate VPN") attempted = true;
                        return 29;
                    }, delegate { throw new InvalidOperationException("helper unavailable"); });
                    throw new Exception("Missing helper was ignored");
                }
                catch (InvalidOperationException) { }
                if (attempted) throw new Exception("Driver installation attempted without a ready helper");
                Console.WriteLine("PASS: a helper startup failure prevents driver installation");
                bool secondReady = false;
                Engine.EnsureNic("VPN2", delegate(string command) {
                    if (command == "NicGetSetting VPN2") return secondReady ? 0 : 29;
                    if (command == "NicCreate VPN2") { secondReady = true; return 0; }
                    throw new Exception("Unexpected second adapter command");
                }, delegate { });
                if (!secondReady) throw new Exception("Missing second adapter");
                try {
                    Engine.EnsureNic("Arbitrary", delegate { throw new Exception("Invalid name reached RPC"); }, delegate { });
                    throw new Exception("Invalid name accepted");
                } catch (System.IO.InvalidDataException) { }
                Console.WriteLine("PASS: only the two official adapter names are accepted");
                return 0;
            }
            catch (Exception error)
            {
                Console.Error.WriteLine("FAIL: " + error.Message);
                return 1;
            }
        }
    }
}
