using System;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("公司网络")]
[assembly: AssemblyDescription("Company Network Client")]
[assembly: AssemblyVersion("1.3.0.0")]
[assembly: AssemblyFileVersion("1.3.0.0")]

namespace CompanyNetwork
{
    internal static class Program
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(uint processId);

        [STAThread]
        private static int Main(string[] args)
        {
            string action = args.Length == 0 ? "--ui" : args[0];
            bool console = action != "--ui";
            if (console)
            {
                AttachConsole(0xFFFFFFFF);
                try { Console.OutputEncoding = new UTF8Encoding(false); } catch (IOException) { }
            }
            try
            {
                if (args.Length > 1 || Array.IndexOf(new string[] { "--ui", "--inspect", "--install-engine", "--prepare-only", "--connect", "--disconnect", "--remove", "--gpt" }, action) < 0)
                    throw new AppProblem("invalid_arguments", "无法识别此操作，请直接打开应用。");
                if (!Environment.Is64BitOperatingSystem) throw new AppProblem("windows_x64_required", "此安装包适用于 64 位 Windows，请联系管理员。");
                AppPayload payload = AppPayload.Read();
                // The UAC child must not acquire its waiting parent's per-user operation mutex.
                if (action == "--install-engine")
                {
                    Engine.Install(payload);
                    WriteJson(new { ok = true, action = action, message = "网络组件已准备完成。" });
                    return 0;
                }
                UserInstall user = new UserInstall(payload);
                if (action == "--inspect")
                {
                    Engine engine = Engine.Find();
                    WriteJson(new {
                        ok = true, resource = AppPayload.ResourceName, payloadFileCount = payload.Files.Count,
                        appVersion = Assembly.GetExecutingAssembly().GetName().Version.ToString(),
                        server = payload.Server, hub = payload.Hub, expiresAt = payload.ExpiresAt.ToString("o"),
                        expired = false, expirationEnforced = false, gptUrl = payload.Gpt.AbsoluteUri,
                        accountName = user.Account, localDirectory = user.DirectoryPath,
                        serviceStatus = Engine.ServiceStatus(), engineDirectory = engine == null ? null : engine.DirectoryPath,
                        reusedExistingClient = engine != null && engine.Reused,
                        uiHelperReady = Engine.UiHelperReady(),
                        caSha256 = BootstrapCore.ExpectedCaSha256, caPresent = UserInstall.HasCa(),
                        caAddedByApp = user.State != null && user.State.CaAdded,
                        accountOwnedByApp = user.State != null && user.State.AccountOwned,
                        transportAccountName = user.TransportAccount,
                        transportAccountOwned = user.State != null && user.State.TransportOwned,
                        configurationVersion = user.State == null ? 0 : user.State.ConfigurationVersion,
                        requestedExecutionLevel = "asInvoker", architecture = "x64"
                    });
                    return 0;
                }
                if (action == "--ui")
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    using (UiInstance instance = new UiInstance(user.Sid))
                    {
                        if (!instance.IsFirst) { instance.Activate(); return 0; }
                        using (MainForm form = new MainForm(user, instance)) Application.Run(form);
                    }
                    return 0;
                }
                string result = Execute(user, action, delegate { });
                WriteJson(new { ok = true, action = action, message = result });
                return 0;
            }
            catch (Exception e)
            {
                AppProblem problem = Explain(e);
                if (console) WriteJson(new { ok = false, code = problem.Code, message = problem.Message, nativeError = problem.NativeError });
                else MessageBox.Show(problem.Message, "公司网络", MessageBoxButtons.OK, MessageBoxIcon.Information);
                if (action == "--install-engine" && problem.Code == "adapter_install_failed" && problem.NativeError >= 0 && problem.NativeError < 1000)
                    return 1000 + problem.NativeError;
                if (action == "--install-engine" && problem.Code == "ui_helper_unavailable") return 900;
                return 1;
            }
        }

        internal static string Execute(UserInstall user, string action, Action<string> progress)
        {
            using (OperationController controller = new OperationController(user))
                return controller.Execute(action, progress);
        }

        internal static AppProblem Explain(Exception exception)
        {
            while (exception is AggregateException || exception is TargetInvocationException)
                exception = exception.InnerException ?? exception;
            AppProblem problem = exception as AppProblem;
            if (problem != null) return problem;
            Win32Exception win32 = exception as Win32Exception;
            if (win32 != null && win32.NativeErrorCode == 1223)
                return new AppProblem("elevation_cancelled", "已取消安装。需要时可重新选择“安装并连接”。");
            if (exception is InvalidDataException || exception is System.Security.Cryptography.CryptographicException)
                return new AppProblem("package_validation_failed", "安装包校验未通过，请向管理员重新获取完整安装包。");
            if (exception is UnauthorizedAccessException)
                return new AppProblem("access_denied", "系统没有允许此操作，请联系管理员检查权限。");
            if (exception is IOException)
                return new AppProblem("file_operation_failed", "配置文件暂时无法保存，请关闭其他公司网络窗口后重试。");
            return new AppProblem("operation_failed", "此操作未能完成，请联系管理员协助处理。");
        }

        private static void WriteJson(object value)
        {
            Console.WriteLine(AppPayload.Json().Serialize(value));
        }
    }

    internal sealed class UiInstance : IDisposable
    {
        readonly Mutex mutex;
        internal readonly EventWaitHandle ShowRequest;
        internal readonly bool IsFirst;
        internal UiInstance(string sid) {
            mutex = new Mutex(true, @"Local\CompanyNetwork.Window." + sid, out IsFirst);
            ShowRequest = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\CompanyNetwork.Show." + sid);
        }
        internal void Activate() { ShowRequest.Set(); }
        public void Dispose() { ShowRequest.Dispose(); if(IsFirst) mutex.ReleaseMutex(); mutex.Dispose(); }
    }

    internal sealed class MainForm : Form
    {
        readonly UserInstall user;
        readonly OperationController controller;
        readonly UiInstance instance;
        readonly Label status;
        readonly Button connect, disconnect, remove;
        readonly NotifyIcon tray;
        readonly System.Windows.Forms.Timer timer;
        bool busy, polling, exiting;
        string facts = "unknown";
        DateTime started;
        string operationMessage = "";
        string lastFailure = "";
        internal MainForm(UserInstall installation, UiInstance windowInstance)
        {
            user = installation; instance = windowInstance; controller = new OperationController(user);
            Text = "公司网络 · 1.3"; Font = new Font("Microsoft YaHei UI", 10F);
            Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);
            StartPosition = FormStartPosition.CenterScreen; FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; ClientSize = new Size(540, 310);
            Controls.Add(new Label { Text = "公司网络", Font = new Font(Font.FontFamily,18F,FontStyle.Bold), Location = new Point(26,23), AutoSize = true });
            Controls.Add(new Label { Text = "使用个人账号连接；收起后可从桌面或托盘找回", Location = new Point(28,68), AutoSize = true });
            connect = new Button { Text = "安装并连接", Location = new Point(29,106), Size = new Size(190,43) };
            disconnect = new Button { Text = "断开 / 取消", Location = new Point(230,106), Size = new Size(130,43) };
            Button gpt = new Button { Text = "打开 GPT", Location = new Point(372,106), Size = new Size(135,43) };
            status = new Label { Text = "正在读取实际连接状态…", Location = new Point(28,168), Size = new Size(480,70) };
            remove = new Button { Text = "移除此配置", Location = new Point(372,257), Size = new Size(135,32) };
            Controls.AddRange(new Control[] { connect, disconnect, gpt, status, remove });
            ContextMenuStrip menu = new ContextMenuStrip();
            menu.Items.Add("显示窗口", null, delegate { RestoreWindow(); });
            menu.Items.Add("断开 / 取消连接", null, async delegate { await Stop(false); });
            menu.Items.Add("打开 GPT", null, async delegate { await Perform("--gpt"); });
            menu.Items.Add("断开并退出", null, async delegate { await Stop(true); });
            tray = new NotifyIcon { Icon = Icon, Text = "公司网络：正在读取状态", Visible = true, ContextMenuStrip = menu };
            tray.DoubleClick += delegate { RestoreWindow(); };
            connect.Click += async delegate { await Perform("--connect"); };
            disconnect.Click += async delegate { await Stop(false); };
            gpt.Click += async delegate { await Perform("--gpt"); };
            remove.Click += async delegate { if(MessageBox.Show(this,"移除本应用拥有的个人配置？","公司网络",MessageBoxButtons.OKCancel) == DialogResult.OK) await Perform("--remove"); };
            Resize += delegate { if(WindowState == FormWindowState.Minimized) Hide(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if(exiting) return;
                if(busy || facts != "disconnected") {
                    e.Cancel = true; Hide(); tray.ShowBalloonTip(5000,"公司网络仍在运行","关窗仅收至托盘。需要结束访问时，请选择“断开并退出”；桌面入口可以找回窗口。",ToolTipIcon.Info);
                }
            };
            timer = new System.Windows.Forms.Timer { Interval = 1000 };
            timer.Tick += async delegate {
                if(instance.ShowRequest.WaitOne(0)) RestoreWindow();
                if(busy) { if((DateTime.UtcNow-started).TotalSeconds >= 10) status.Text = operationMessage + "\n仍未完成，正在等待组件响应或回收；请保留此窗口。"; return; }
                await RefreshState();
            };
            Shown += async delegate { timer.Start(); await RefreshState(); };
        }
        void RestoreWindow() { Show(); WindowState = FormWindowState.Normal; Activate(); }
        async Task RefreshState() {
            if(polling || busy) return; polling = true;
            try { ConnectionSnapshot snapshot = await Task.Run(delegate { using(OperationController reader = new OperationController(new UserInstall(user.Payload))) return reader.Read(); }); facts = snapshot.Kind; status.Text = (lastFailure.Length == 0 ? "" : lastFailure + "\n") + snapshot.Message; tray.Text = "公司网络：" + (facts == "connected" ? "已连接" : facts == "disconnected" ? "已断开" : "恢复中"); }
            catch(Exception e) { facts = "unknown"; status.Text = "状态未确认：" + Program.Explain(e).Message; tray.Text = "公司网络：状态未确认"; }
            finally { polling = false; }
        }
        async Task Stop(bool exit) {
            controller.RequestStop();
            if(busy) { operationMessage = "已请求取消；正在等待当前操作回收连接。"; status.Text = operationMessage; while(busy) await Task.Delay(100); }
            while(polling) await Task.Delay(100);
            bool success = await Perform("--disconnect");
            if(exit && success && facts == "disconnected") { exiting = true; Close(); }
        }
        async Task<bool> Perform(string action) {
            if(busy || polling) return false;
            busy = true; lastFailure = ""; started = DateTime.UtcNow;
            tray.Text = action == "--disconnect" ? "公司网络：正在断开" : action == "--connect" ? "公司网络：正在连接" : "公司网络：正在操作"; operationMessage = action == "--disconnect" ? "正在断开并确认两层会话…" : "正在执行，请稍候…";
            status.Text = operationMessage; connect.Enabled = remove.Enabled = false;
            bool success = false;
            try {
                string result = await Task.Run(delegate { return controller.Execute(action, delegate(string p) { if(!IsDisposed) BeginInvoke((Action)delegate { operationMessage = p; status.Text = p; }); }); });
                status.Text = result; success = true;
            } catch(Exception e) { operationMessage = Program.Explain(e).Message; lastFailure = operationMessage; status.Text = operationMessage; }
            finally { busy = false; connect.Enabled = remove.Enabled = true; }
            await RefreshState();
            return success;
        }
        protected override void Dispose(bool disposing) {
            if(disposing) { timer.Stop(); timer.Dispose(); tray.Visible = false; tray.Dispose(); controller.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
