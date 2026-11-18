# herdr-lark-bridge

[English](README.md)

Herdr 里的 agent 等待审批或完成一轮时，机器人会给你发 Lark 私信。引用回复这条私信，内容会作为按键或提示词送进对应 agent 的窗格。没有 LLM 参与，路由是确定性的，只听配对 owner 的话，审批只接受按键。

## 要求

- 后台服务仅支持 macOS。Linux 前台运行理论上可用，但未测试。
- herdr 0.9.3 或更新（测试所用版本），并已运行。
- uv 和 Python 3.12 及以上（uv 会自动安装 Python）。
- 国际版 Lark 账号。飞书（中国）可通过配置项使用，但未测试。

## 快速开始

1. **创建 Lark 应用。** 打开 [open.larksuite.com/app](https://open.larksuite.com/app)（飞书：[open.feishu.cn/app](https://open.feishu.cn/app)），用 **Built for agents** 的 Create 按钮创建。它会预先配好机器人、长连接事件和权限，并自动发布。在凭证页复制 App ID 和 App Secret。
2. **安装。** `uv tool install git+https://github.com/silex-ai-lab/herdr-lark-bridge`
3. **配置。** 运行 `herdr-lark setup`。依次输入域名、App ID、App Secret（输入不回显），它会保存凭证（权限 0600）、向 Lark 验证、询问是否安装后台服务，并打印 6 位配对码。
4. **私信配对码。** 在 Lark 里与机器人单聊，10 分钟内发送这 6 位数字。机器人回复“配对成功”后，你就是唯一的 owner。
5. **完成。** 运行 `herdr-lark send-test` 发一条测试消息。有问题时运行 `herdr-lark doctor`。

`setup` 可以重复运行：回车保留已保存的值，已有 owner 时不会再次开启配对。

## 回复规则

引用回复某条通知即可操作对应的 agent。

- **等待审批。** 只含按键名（`y n 0-9 enter esc tab up down left right space`，空格分隔）时按键发送，例如 `1` 或 `down down enter`。以 `输入 ` 或 `text ` 开头时，其后内容原样输入并回车。其他内容（包括 yes、no、是、否）不会执行，机器人会说明这两种写法。
- **已完成。** 内容作为新提示词发送。
- **不引用。** 仅当恰好有一条待处理通知且发出不超过 `shortcut_minutes` 分钟时生效。

在 `~/.config/herdr-lark/config.toml` 里设置 `lang = "en"` 可把所有消息改为英文，默认 `zh`。两种前缀在任何语言下都有效。

## 命令

Lark 内：`/list`、`/read <编号或名称>`、`/to <编号或名称> <文字>`、`/help`。

终端：`herdr-lark setup`、`doctor`、`service install|uninstall|status`、`run`、`pair`、`unpair`、`status`、`send-test`。

## 安全与限制

安全模型、发送到 Lark 的终端内容、配置项默认值、已知限制（笔记本休眠期间没有通知、连接打开但已失效时无法检测、发送与保存之间崩溃可能重复通知）、故障排查和卸载方式见 [README.md](README.md)。

## 卸载

```
herdr-lark service uninstall
uv tool uninstall herdr-lark-bridge
rm -r ~/.config/herdr-lark ~/.local/state/herdr-lark ~/Library/Logs/herdr-lark
```
