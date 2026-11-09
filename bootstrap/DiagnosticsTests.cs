using System;
using System.Collections.Generic;
using System.Threading;

namespace CompanyNetwork
{
    internal static class DiagnosticsTests
    {
        static int count;
        static void Check(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
            count++;
        }

        [STAThread]
        static void Main()
        {
            string privateValue = "https://alice:password@example.com/docx/private?token=login#secret eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature";
            bool connected = false;
            using (var controller = new OperationController("diagnostics-test-" + Guid.NewGuid().ToString("N"),
                delegate(string action, Action<string> progress, Action check) {
                    progress(privateValue);
                    if (action == "--connect") connected = true;
                    if (action == "--disconnect") connected = false;
                    return privateValue;
                }, delegate { return new ConnectionSnapshot { Outer = connected, Inner = connected, Route = connected, SessionsReady = connected }; }))
            {
                controller.Execute("--connect", delegate { });
                string report = Diagnostics.Collect(controller.Read, new Dictionary<string, Func<object>> {
                    { "proxy", delegate { return new { server = privateValue, authorization = "Bearer private", Cookie = "private" }; } },
                    { "broken", delegate { throw new AppProblem("collector_failed", privateValue, 123); } },
                    { "healthy", delegate { return "still collected"; } }
                });
                Check(report.Contains("connected") && report.Contains("outerActive") && report.Contains("sessionsReady"), "real controller snapshot exported");
                Check(report.Contains("transition") && report.Contains("phase") && report.Contains("elapsedMs"), "monotonic operation journal exported");
                Check(report.Contains("collector_failed") && report.Contains("123") && report.Contains("still collected"), "partial failure preserves other collectors and native code");
                Check(!report.Contains("alice") && !report.Contains("password@") && !report.Contains("token=login") && !report.Contains("eyJ") && !report.Contains("Bearer private"), "application export redacts secrets");
                Check(report.Contains("businessValidation") && report.Contains("未验收"), "business acceptance separated");

                var started = new ManualResetEvent(false);
                var release = new ManualResetEvent(false);
                var export = System.Threading.Tasks.Task.Run(delegate {
                    return Diagnostics.Collect(controller.Read, new Dictionary<string, Func<object>> {
                        { "slow", delegate { started.Set(); release.WaitOne(); return true; } }
                    });
                });
                Check(started.WaitOne(2000), "background collector started");
                controller.RequestStop();
                controller.Execute("--disconnect", delegate { });
                Check(controller.Read().Kind == "disconnected" && !export.IsCompleted, "disconnect independent of diagnostic collector");
                release.Set();
                Check(export.Wait(2000), "collector finishes after release");
            }
            using (var failing = new OperationController("diagnostics-failure-" + Guid.NewGuid().ToString("N"),
                delegate { throw new AppProblem("native_failure", privateValue, 789); },
                delegate { throw new AppProblem("snapshot_failure", privateValue, 456); }))
            {
                try { failing.Execute("--gpt", delegate { }); } catch (AppProblem) { }
                string report = Diagnostics.Collect(failing.Read, new Dictionary<string, Func<object>>());
                Check(report.Contains("native_failure") && report.Contains("789") && report.Contains("snapshot_failure") && report.Contains("456"), "operation and read errors survive application boundary");
                Check(!report.Contains("token=login") && !report.Contains("alice"), "failure messages never exported");
            }
            TestWindowLifetime();
            Console.WriteLine("Diagnostics: " + count + " checks passed.");
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern IntPtr SendMessage(IntPtr window, int message, IntPtr command, IntPtr parameter);

        static void CloseThroughNonClientX(ClientHost host)
        {
            MainForm original = host.Window;
            // Exercise the native system close command used by the title-bar X.
            SendMessage(original.Handle, 0x0112, new IntPtr(0xF060), IntPtr.Zero);
            System.Windows.Forms.Application.DoEvents();
            Check(original.IsDisposed && host.Window == null, "non-client X actually disposes window");
            MainForm reopened = host.OpenWindow(false);
            Check(!ReferenceEquals(original, reopened) && !reopened.IsDisposed, "background host recreates window without reconnecting");
        }

        static void Pump(System.Threading.Tasks.Task task)
        {
            var timeout = System.Diagnostics.Stopwatch.StartNew();
            while (!task.IsCompleted && timeout.ElapsedMilliseconds < 3000)
            {
                System.Windows.Forms.Application.DoEvents();
                Thread.Sleep(10);
            }
            Check(task.IsCompleted, "background operation completed after window recreation");
            task.GetAwaiter().GetResult();
        }

        static void TestWindowLifetime()
        {
            var entered = new ManualResetEvent(false);
            var release = new ManualResetEvent(false);
            int disconnects = 0;
            bool slowRead = false;
            Func<ConnectionSnapshot> read = delegate {
                if (slowRead) { entered.Set(); release.WaitOne(); }
                return new ConnectionSnapshot { Outer = true, Inner = true, Route = true, SessionsReady = true };
            };
            using (var instance = new UiInstance("window-test-" + Guid.NewGuid().ToString("N")))
            using (var operation = new OperationController("window-operation-" + Guid.NewGuid().ToString("N"),
                delegate(string action, Action<string> progress, Action check) {
                    if (action == "--disconnect") { disconnects++; throw new AppProblem("disconnect_failed", "still active"); }
                    entered.Set(); release.WaitOne(); return "connected";
                }, read))
            using (var host = new ClientHost(operation, read, instance, true, false))
            {
                CloseThroughNonClientX(host); // Initially unknown.
                var connecting = host.Perform("--connect");
                Check(entered.WaitOne(2000), "connection is in flight before X");
                CloseThroughNonClientX(host);
                Check(!connecting.IsCompleted && disconnects == 0, "X never cancels or disconnects an in-flight connection");
                release.Set();
                Pump(connecting);
                CloseThroughNonClientX(host); // Connected.
                entered.Reset(); release.Reset(); slowRead = true;
                var polling = host.RefreshState();
                Check(entered.WaitOne(2000), "state query is in flight before X");
                CloseThroughNonClientX(host);
                Check(!polling.IsCompleted && disconnects == 0, "X never waits for query or disconnects VPN");
                release.Set(); slowRead = false;
                Pump(polling);
                Pump(host.Stop(false));
                Check(disconnects == 1 && host.Window != null && !host.Window.IsDisposed, "explicit disconnect failure keeps control window usable");
                CloseThroughNonClientX(host); // Failure must also retain standard close behavior.
            }
        }

    }
}
