# 公司网络 1.3

Windows 10/11 x64 员工客户端：通过一个“公司网络”入口连接、查看状态、打开 GPT、断开并导出诊断。右上角 × 直接关闭主窗口，连接和后台操作继续；桌面入口或托盘可重新打开窗口。使用方法见 [员工说明.txt](员工说明.txt)。

1.3 的入口、生命周期和诊断已有代码验证，飞书断连、授权文档及外网性能仍待现场验收。当前已知结果及发布门槛见 [实施记录](docs/implementation.md)，1.2 历史结果保留在 [INTEGRATION.md](INTEGRATION.md)。

## 构建与打包

需要 Windows x64、.NET Framework 4.8 编译器、Git 和 Python 3.11 或更新版本。源码 ZIP 根目录含构建需要的公开 `company.payload.zip`；仓库本身不提交载荷，维护者须从受控交付资料取得。

```powershell
New-Item -ItemType Directory -Force build
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Build.ps1 -PayloadZipPath company.payload.zip -OutputPath build/CompanyNetwork.exe
python tools/package_release.py --exe build/CompanyNetwork.exe --source-repo . --payload company.payload.zip --output-dir build/release-1.3-candidate-01
```

打包是一条命令，四个路径均须显式提供，也支持绝对路径。输出目录必须尚不存在；重复执行使用新目录，原 1.2 及既有交付路径保持原样。源码文件以指定仓库的 `git ls-files` 为准，新文件先 `git add`；未提交的跟踪文件修改会进入源码快照，并在摘要中标记。

输出为员工 ZIP、源码 ZIP、`SHA256SUMS.txt`、`验证摘要.json`。员工 ZIP 只含 EXE、中文说明、引擎许可与内部校验清单；源码 ZIP 包含受允许的跟踪源码、文档、图标、公开载荷和构建清单。脚本拒绝不在源码允许范围的跟踪文件，不读取 Git 历史、调查目录、忽略的构建文件或员工本地配置。

脚本核对 EXE 的 `1.3.0.0` 文件版本、内嵌载荷与显式载荷的 SHA256、载荷的 11 个固定条目，以及输出 ZIP 的条目集合、CRC 和逐项哈希。相同输入、跟踪源码快照、Git HEAD 及工作区修改标记，在同一 Python/zlib 环境中生成相同字节。输入文件应在命令运行期间保持不变。

在解压后的源码目录复现打包时，先 `git init`，再执行 `git add .gitignore README.md 员工说明.txt INTEGRATION.md bootstrap docs tools`，提交这些源码文件；`company.payload.zip` 和 `BUILD-MANIFEST.json` 保持不跟踪。使用源码 ZIP 中的载荷重新执行构建；构建清单保留了原仓库 HEAD 与逐文件哈希。源码 ZIP 自身不带 `.git`。

用 `Get-FileHash -Algorithm SHA256 <文件>` 对照清单。校验值用于核对字节完整性，不是数字签名或业务验收。EXE 与源码分别记录哈希；脚本只核对内嵌载荷，最终维护者仍需确认该 EXE 来自交付的同一源码构建。

## 验证与部署

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Test-Core.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Test-Adapter.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Test-Lifecycle.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Test-Diagnostics.ps1
python -m unittest discover -s tools -p test_network_tools.py -v
```

管理员先在测试电脑完成最终构建的 × 关闭/桌面及托盘找回、真实连接/取消/断开、新装/1.2 升级/重复升级，再执行 [规格验收](docs/spec.md) 的业务流程。公司外电脑、Chrome 授权文档及 60 分钟消息稳定性分别记录。网络采样和候选规则的校验、部署与回滚步骤见 [网络工具说明](tools/README.md)。

批准后将员工 ZIP 解压到新目录运行 EXE，按组件安装提示操作，使用员工原个人账号；保留原始 1.2 交付包。升级前从托盘明确“断开并退出”旧后台，确认两层断开后启动新版。回滚同样先断开并退出新版，再从原 1.2 包启动；不要删除个人配置、共享引擎或网卡。1.3 未承诺任意跨版本配置的逆向迁移，先在测试电脑验证。网络候选规则由管理员独立审阅和部署，客户端打包不修改网关。
