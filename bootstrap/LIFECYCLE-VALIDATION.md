# 1.3 客户端生命周期验证（2026-11-09）

本工作区只修改 bootstrap 客户端，不修改载荷和服务器，不执行真实连接、安装或当前用户桌面迁移。

- C#5 / x64 / .NET Framework 编译成功，真实 company.payload.zip 已嵌入，程序集版本 1.3.0.0。
- Test-Core.ps1：19 项通过；Test-Adapter.ps1：5 项通过。
- Test-Lifecycle.ps1：16 项通过，包含两项并发入口等待条件断言；覆盖状态恢复、断开失败、跨控制器停止、重复连接拒绝、不可中断迟到成功回收、待连接/旧路由不能冒充已就绪、清理失败、外层残留和查询失败，以及隔离真实 .lnk 新装、升级、重复升级和归属冲突。
- git diff --check 通过。

应用接口位于 OperationController.cs。UI 与原 CLI Execute 共用 OperationController(UserInstall)。Execute(action, progress) 串行化修改；RequestStop() 提前发布停止意图；Read() 返回 Outer/Inner 活跃事实、Route、SessionsReady 与 Kind；未知状态通过异常显式传播。Transition 的参数仅为状态名，便于后续诊断接入。

限制：命名对象使用 Local 命名空间，保证同一用户当前 Windows 登录会话内单交互窗口与操作协调；没有声称支持同一账号跨并行 RDP 登录会话控制同一窗口。正在执行的 UAC/官方安装/登录组件调用无法强制终止，停止意图会在返回后阻止继续连接，并执行确认回收；10 秒后界面明确显示仍未完成。窗口/托盘、真实账号认证、休眠和外网业务验证须由父任务继续验收。快捷方式升级发生在原安装并连接流程准备阶段，单纯打开未配置的程序不会自行安装或修改桌面。


## 诊断与正常关闭补充验证

2026-11-09：ClientHost ApplicationContext 持有后台控制器、托盘和定时器；主窗口无 FormClosing 拦截，X/Alt+F4 与断开操作独立。关闭会释放 Form；桌面/托盘按需重建。该行为按用户最新明确要求替代此前关窗收至托盘的约定。最小化仍可收起。

- Test-Diagnostics.ps1：28 项检查通过，包含真实 OperationController 导出脱敏与错误码、局部失败不中断其他采集、后台采集不阻止断开。
- 隐藏窗口通过原生 WM_SYSCOMMAND/SC_CLOSE 验证 unknown、连接操作中、已连接、状态查询中、断开失败后均真实释放；后台不因 X 发起取消/断开，能重建控制窗口。测试不会显示窗口或托盘，不调用真实 VPN。
- 现有 Core 19、Adapter 5、Lifecycle 16 项继续通过。真实 payload、C#5/.NET Framework x64 构建成功。
- 网络工具单元测试 8 项通过，覆盖冷/热进程与缓存边界、失败保留、URL限制、候选幂等、冲突、原配置及hash保护。具体用法和未验收业务边界见 tools/README.md。

这些检查不替代受影响实机的鼠标非客户端 X、托盘/桌面重开、飞书消息/授权文档与公司外网络验收；本分支未连接真实 VPN、修改生产网关或运行真实网络测速。
