# Process_Audio_Capturer （见源码内 VERSION 常量）

> **一句话**：进程音频转字幕工具：只抓指定进程输出的声音，用 vosk 离线识别实时转成字幕，音频设备与采样率可选。想把某个软件或播放器里的语音变成文字、又不希望录进整机声音时用。PyQt5 编写。

---

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 零基础入门（5 分钟跑起来）](#2-零基础入门5-分钟跑起来)
- [3. 功能与界面](#3-功能与界面)
- [4. 命令行参数](#4-命令行参数)
- [5. 配置文件与数据](#5-配置文件与数据)
- [6. 工作原理（技术参考）](#6-工作原理技术参考)
- [7. 排错手册](#7-排错手册)
- [8. 常见问题 FAQ](#8-常见问题-faq)
- [9. 目录结构](#9-目录结构)
- [10. 开发与构建](#10-开发与构建)
- [11. 已知限制与安全说明](#11-已知限制与安全说明)
- [12. 许可](#12-许可)

## 1. 这是什么

| 项目 | 说明 |
| --- | --- |
| 程序名 | `Process_Audio_Capturer` |
| 当前版本 | （见源码内 VERSION 常量） |
| 主程序 | `Process_Audio_Capturer.py` |
| 界面技术 | PyQt5（Qt5 社区绑定） |
| 语言 / 运行平台 | Python 3.10 / Windows |
| 源码规模 | 根目录及子模块共 23 个 .py 文件 |
| 仓库 | https://github.com/duma520/Process_Audio_Capturer |

## 2. 零基础入门（5 分钟跑起来）

### 第 1 步：装 Python

1. 打开 <https://www.python.org/downloads/windows/>，下载 Python 3.10 或更新版本。
2. 安装时**务必勾选** `Add python.exe to PATH`（安装向导第一页最下方）。
3. 装完按 `Win + R` 输入 `cmd`，敲 `python --version`，能看到版本号就成功了。

### 第 2 步：拿到源码

- **下载压缩包**：在本仓库 Releases 页下载 `Process_Audio_Capturer-*.zip`，解压到任意目录。
- **git 克隆**：`git clone https://github.com/duma520/Process_Audio_Capturer.git`

### 第 3 步：装依赖

在源码目录打开命令行，执行：

```
pip install PyAudio PyQt5 numpy psutil pywin32 requests sounddevice speech_recognition vosk webrtcvad
```

> 清单是从源码的实际 import 汇总出来的；若某个包名不准确，以 pip 报错提示的正确包名为准。

### 第 4 步：启动

```bat
python Process_Audio_Capturer.py
```

目录里还带了 `1.bat`，双击等同于上面的命令（前提是 Python 在 PATH 里）。

## 3. 功能与界面

> 本节只列源码里能确认的事实；具体按钮与交互以运行后的界面为准。

| 维度 | 实际情况 |
| --- | --- |
| 界面框架 | PyQt5（Qt5 社区绑定） |
| 是否有 main 入口 | 是，可直接 python 主程序.py 运行 |
| 第三方依赖数 | 10 个 |

## 4. 命令行参数

该程序没有定义命令行参数，直接运行即可（操作都在界面里完成）。

## 5. 配置文件与数据

源码目录里可见的配置/数据文件：

- `audio_capturer_config.json`
- `settings.json`

这些文件在运行时读写；个人数据（路径、账号、历史记录）不会提交到仓库，由 .gitignore 排除，首次运行会自动生成。

## 6. 工作原理（技术参考）

```
用户操作 → PyQt5 → 业务逻辑 → 结果输出
```

- 入口文件 `Process_Audio_Capturer.py`，带 if __name__ == '__main__' 保护。
- 依赖的第三方库：`PyAudio`、`PyQt5`、`numpy`、`psutil`、`pywin32`、`requests`、`sounddevice`、`speech_recognition`、`vosk`、`webrtcvad`。
- 全部业务逻辑在仓库内可见，没有编译产物、没有联网下发代码。

## 7. 排错手册

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| python 不是内部或外部命令 | 安装时没勾 PATH | 重装 Python 并勾选 Add python.exe to PATH，或改用 py 命令 |
| ModuleNotFoundError: No module named xxx | 依赖没装 | 按第 3 步 pip install 对应包 |
| 双击 .bat 一闪而过 | 出错后窗口立即关闭 | 用 cmd 进入目录再执行命令，看清报错 |
| 界面显示乱码 | 控制台编码不是 UTF-8 | 先执行 chcp 65001，或用 python -X utf8 主程序.py |
| 杀毒软件拦截 | 未签名脚本被误判 | 加入信任/白名单；本项目只提供源码，可自行审阅 |

## 8. 常见问题 FAQ

**Q1：需要装 Visual Studio 之类的编译工具吗？**
A：不需要。这里只提供 Python 源码，pip 装的是预编译轮子。

**Q2：能在 macOS / Linux 上跑吗？**
A：本项目按 Windows 环境开发与验证；其他系统未测试，可能需要改路径与系统 API 调用。

**Q3：为什么 Releases 里只有源码 zip，没有 exe？**
A：只分发源码，避免二进制被误判；需要 exe 请按第 10 节自行打包。

**Q4：改了代码怎么运行？**
A：直接 python 主程序.py，改动立即生效，无需编译。

**Q5：数据存在哪？会不会被上传？**
A：只存在本机（程序目录或用户目录）。本程序不含上传逻辑。

**Q6：怎么反馈问题？**
A：到 https://github.com/duma520/Process_Audio_Capturer/issues 提 Issue，附上报错原文与复现步骤。

## 9. 目录结构

```
models/
vosk-model-small-cn-0.22/
vosk-model-spk-0.4/
历史/
1.bat
Process_Audio_Capturer - 20.0.py
Process_Audio_Capturer - 21.0.py
Process_Audio_Capturer - 21.1.py
Process_Audio_Capturer.py
README.md
audio_capturer_config.json
settings.json
vosk-model-cn-0.22.zip
vosk-model-cn-kaldi-multicn-0.15.zip
web.txt
改来改去还是声道不适配，暂停开发.txt
models\vosk-model-small-cn-0.22/
models\vosk-model-small-cn-0.22\README
vosk-model-small-cn-0.22\am/
vosk-model-small-cn-0.22\conf/
vosk-model-small-cn-0.22\graph/
vosk-model-small-cn-0.22\ivector/
vosk-model-small-cn-0.22\README
vosk-model-small-cn-0.22\am\final.mdl
vosk-model-small-cn-0.22\conf\mfcc.conf
vosk-model-small-cn-0.22\conf\model.conf
vosk-model-small-cn-0.22\graph\Gr.fst
vosk-model-small-cn-0.22\graph\HCLr.fst
vosk-model-small-cn-0.22\graph\disambig_tid.int
vosk-model-small-cn-0.22\ivector\final.dubm
vosk-model-small-cn-0.22\ivector\final.ie
vosk-model-small-cn-0.22\ivector\final.mat
vosk-model-small-cn-0.22\ivector\global_cmvn.stats
vosk-model-small-cn-0.22\ivector\online_cmvn.conf
vosk-model-small-cn-0.22\ivector\splice.conf
vosk-model-spk-0.4\README.txt
vosk-model-spk-0.4\final.ext.raw
vosk-model-spk-0.4\mean.vec
vosk-model-spk-0.4\mfcc.conf
vosk-model-spk-0.4\transform.mat
历史\VBCABLE_Driver_Pack45/
历史\Process_Audio_Capturer - 1.0.py
历史\Process_Audio_Capturer - 10.0.py
历史\Process_Audio_Capturer - 11.0 t1.py
历史\Process_Audio_Capturer - 12.0 t1.py
```

## 10. 开发与构建

- 直接运行（开发态）：`python Process_Audio_Capturer.py`
- 语法自检：`python -m py_compile Process_Audio_Capturer.py`
- 打包 exe（可选）：装 pyinstaller 后执行 `pyinstaller -F -w Process_Audio_Capturer.py`

## 11. 已知限制与安全说明

- 只提供源码，不提供预编译二进制。
- 仓库不含任何凭据；.env / *.pem / *.key / 日志与运行期数据均在 .gitignore 中排除。
- 若程序需要联网，请在源码中确认目标地址后再运行。

## 12. 许可

AGPL-3.0，详见仓库根目录 LICENSE。
