# 公司网络 1.2 Windows 启动器

C#5/.NET Framework4.8、WinForms、Windows x64、asInvoker。内置成熟 SoftEther 4.44 官方文件，原始签名有效；外层封装未签名。员工 API 地址完整保留 http://192.168.1.29:8080/v1，网页为同地址根路径。

## 构建和资源

源包根的 company.payload.zip 包含11项：engine/下 vpnclient_x64.exe、vpncmd_x64.exe、vpncmgr_x64.exe、vpninstall.exe、hamcore.se2、lang.config、LICENSE.txt；另有 profile.vpn、transport.vpn、company-ca.cer、public-config.json。

```powershell
.\bootstrap\Build.ps1 -PayloadZipPath .\company.payload.zip -OutputPath .\CompanyNetwork.exe
.\bootstrap\Test-Core.ps1
.\bootstrap\Test-Adapter.ps1
```

使用系统 Framework64/v4.0.30319/csc.exe，无NuGet。当前19项Core和5项Adapter测试通过；真实验证与边界见INTEGRATION.md。

## 连接与安全边界

外层公开引导身份transport在OFFICE_TRANSPORT中匿名建立连接，只能到公司私有内层的原生VPN TLS端口。内层OFFICE_TRIAL使用员工个人账号、公司原生服务器证书精确固定验证。两层均开启加密及证书检查，软件自动管理，员工只输入一次个人账号。原HTTP内容在员工到公司这段由内层TLS保护。

profile.vpn无员工用户名/密码，设备VPN，内层地址10.253.60.1/tcp:443，固定公司证书；transport.vpn为公开引导身份、设备VPN2、Azure入口证书固定。验证拒绝额外ZIP条目、路径跳转、任意设备名、非公开传输身份或嵌入密码。公开配置仅5个字符串字段。HTTP链接只允许固定192.168.1.29:8080的根路径或/v1；其他HTTP目标拒绝。

外层须同时满足SID会话建立、VPN2地址Preferred、目标最佳路由经过VPN2、公司TLS端口可达，才启动内层。内层须真实建立、NAS最佳路由经过VPN且地址属于10.253.61/24，才能打开GPT。网卡描述允许Windows重装后的受限数字后缀，严格区分VPN与VPN2。HTTP模式无需新增系统根证书；HTTPS模式沿用原CA归属和回收逻辑。

首次安装或缺少网卡时，创建官方VPN/VPN2网卡前启动独立常驻vpnclient_x64.exe /uihelp，并等待localhost:9983就绪。官方驱动helper按Windows策略请求管理员授权，不关闭驱动签名或内存完整性；原生错误码会保留到提示中。

## 操作

无参数打开中文界面。--inspect只读检查，含版本、公开配置、服务状态、外层/内层创建标志；不输出员工用户名密码。--prepare-only在组件齐备时准备或迁移配置，不连接、不提权。--connect等待两层与必要路由真实就绪，失败则断开自己两层。--disconnect断开自己两层。--remove仅移除自己拥有的连接、快捷方式、公开文件和自己新增的CA，保留共享客户端及网卡。--gpt按同样门禁打开原地址。

本用户目录为LocalAppData/CompanyNetwork，本地账号按Windows SID派生。ConfigurationVersion=11迁移旧连接的服务器、Hub、网卡和证书，保留已保存的员工身份；外层单独记录所有权。请关闭旧窗口后升级，避免旧版覆盖新状态。不得把已有vpn_client.config、client_log、私有账号表或GPT认证文件打进包。

1.2.0.0取消客户端本地日期门禁和界面期限标签，个人账号权限由管理员在服务器管理。为兼容既有载荷，public-config.json仍要求5个字符串字段并解析expiresAt，但该日期不阻止安装、连接或打开GPT；--inspect保留expiresAt元数据，expired与expirationEnforced均为false。升级无需修改该日期，服务器端账号或服务权限仍须由管理员独立确认。

实际新电脑首次完整安装与公司外链路仍需测试人员验证；本机已实际新建VPN2。本次1.2在旧截止时间之后完成配置准备、连接、原地址真实GPT请求、外网访问和断开验证。界面已核对不再显示截止日期；已有组件时按钮显示“连接”，新电脑显示“安装并连接”。
