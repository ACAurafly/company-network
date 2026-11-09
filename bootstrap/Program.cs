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
[assembly: AssemblyVersion("1.2.0.0")]
[assembly: AssemblyFileVersion("1.2.0.0")]

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
                    Application.Run(new MainForm(user));
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
            using (Mutex gate = new Mutex(false, @"Local\CompanyNetwork.User." + user.Account))
            {
                bool acquired;
                try { acquired = gate.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new AppProblem("operation_busy", "另一项操作正在进行，请稍后重试。");
                try
                {
                    user.ReloadState();
                    if (action == "--prepare-only") return user.Prepare(false, false, progress);
                    if (action == "--connect") return user.Prepare(true, true, progress);
                    if (action == "--disconnect") return user.Disconnect();
                    if (action == "--remove") return user.Remove();
                    if (action == "--gpt") return user.OpenGpt();
                    throw new AppProblem("invalid_action", "无法识别此操作。");
                }
                finally { gate.ReleaseMutex(); }
            }
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

    internal sealed class MainForm : Form
    {
        private readonly UserInstall user;
        private readonly Label status;
        private readonly Button connect;
        private readonly Button disconnect;
        private readonly Button gpt;
        private readonly Button remove;
        private bool busy;

        internal MainForm(UserInstall installation)
        {
            user = installation;
            Text = "公司网络 · 1.2";
            Font = new Font("Microsoft YaHei UI", 10F);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            ClientSize = new Size(510, 290);
            Label title = new Label { Text = "公司网络", Font = new Font(Font.FontFamily, 18F, FontStyle.Bold), Location = new Point(26, 23), AutoSize = true };
            Label subtitle = new Label { Text = "使用管理员分配的个人账号连接", Location = new Point(28, 67), AutoSize = true };
            connect = new Button { Text = user.State != null && user.State.AccountOwned ? "连接" : "安装并连接", Location = new Point(29, 106), Size = new Size(204, 43) };
            disconnect = new Button { Text = "断开", Location = new Point(246, 106), Size = new Size(105, 43) };
            gpt = new Button { Text = "打开 GPT", Location = new Point(363, 106), Size = new Size(119, 43) };
            status = new Label { Text = "首次使用请允许系统安装确认，然后输入你的个人账号。", Location = new Point(28, 167), Size = new Size(454, 53) };
            remove = new Button { Text = "移除此配置", Location = new Point(363, 236), Size = new Size(119, 32) };
            Controls.AddRange(new Control[] { title, subtitle, connect, disconnect, gpt, status, remove });
            connect.Click += async delegate { await Perform("--connect"); };
            disconnect.Click += async delegate { await Perform("--disconnect"); };
            gpt.Click += async delegate { await Perform("--gpt"); };
            remove.Click += async delegate {
                if (MessageBox.Show(this, "移除此应用创建的个人连接和信任配置？", "公司网络", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) == DialogResult.OK)
                    await Perform("--remove");
            };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
        }

        private async Task Perform(string action)
        {
            busy = true;
            connect.Enabled = disconnect.Enabled = gpt.Enabled = remove.Enabled = false;
            try
            {
                string message = await Task.Run(delegate {
                    return Program.Execute(user, action, delegate(string progress) {
                        BeginInvoke((Action)delegate { status.Text = progress; });
                    });
                });
                status.Text = message;
                connect.Text = user.State != null && user.State.AccountOwned ? "连接" : "安装并连接";
            }
            catch (Exception e) { status.Text = Program.Explain(e).Message; }
            finally
            {
                busy = false;
                connect.Enabled = disconnect.Enabled = gpt.Enabled = remove.Enabled = true;
            }
        }
    }
}
