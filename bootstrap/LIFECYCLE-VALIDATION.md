# 1.3 客户端生命周期验证（2026-11-09）

本工作区只修改 bootstrap 客户端，不修改载荷和服务器，不执行真实连接、安装或当前用户桌面迁移。

- C#5 / x64 / .NET Framework 编译成功，真实 company.payload.zip 已嵌入，程序集版本 1.3.0.0。
- Test-Core.ps1：19 项通过；Test-Adapter.ps1：5 项通过。
- Test-Lifecycle.ps1：16 项通过，包含两项并发入口等待条件断言；覆盖状态恢复、断开失败、跨控制器停止、重复连接拒绝、不可中断迟到成功回收、待连接/旧路由不能冒充已就绪、清理失败、外层残留和查询失败，以及隔离真实 .lnk 新装、升级、重复升级和归属冲突。
- git diff --check 通过。

应用接口位于 OperationController.cs。UI 与原 CLI Execute 共用 OperationController(UserInstall)。Execute(action, progress) 串行化修改；RequestStop() 提前发布停止意图；Read() 返回 Outer/Inner 活跃事实、Route、SessionsReady 与 Kind；未知状态通过异常显式传播。Transition 的参数仅为状态名，便于后续诊断接入。

限制：命名对象使用 Local 命名空间，保证同一用户当前 Windows 登录会话内单交互窗口与操作协调；没有声称支持同一账号跨并行 RDP 登录会话控制同一窗口。正在执行的 UAC/官方安装/登录组件调用无法强制终止，停止意图会在返回后阻止继续连接，并执行确认回收；10 秒后界面明确显示仍未完成。窗口/托盘、真实账号认证、休眠和外网业务验证须由父任务继续验收。快捷方式升级发生在原安装并连接流程准备阶段，单纯打开未配置的程序不会自行安装或修改桌面。
