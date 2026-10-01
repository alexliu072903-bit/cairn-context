# Cairn Context

**[English](README.md) | 中文**

一个 Skill：让新开的 Agent session 找回与当前任务相关、已经确认过的项目决定，你不用再重复解释。

支持 Claude Code、Codex，以及任何能加载 `SKILL.md` 的 Agent。你的决定保存在你自己拥有的仓库里，这个公开仓库只包含 Skill、安装器和模板。

## 它做什么

- 只读取与当前任务有关的决定。Agent 按文件名和标题挑选（见“限制”）。
- 区分已经确认的决定、暂时的倾向、开放的问题和临时实验。信号不清楚时，只问一次。
- 决定变化时保留历史：旧文件不删，新文件用 `supersedes` 指向它。
- 记录你的纠正，错误的判断可以追溯。

这些是给 Agent 的指令，不是强制保证。效果取决于模型遵循指令的能力。

## 安装

克隆本仓库，再用你使用的 Agent 对应的参数运行安装器。

Claude Code：

```bash
bash install.sh --identity "你的名字" --project "your-project" --repository "$HOME/cairn" --claude-code
```

Codex：

```bash
bash install.sh --identity "你的名字" --project "your-project" --repository "$HOME/cairn" --codex
```

两个都装，就同时传两个参数。其他 Agent 请指向它的 skills 目录：

```bash
bash install.sh --identity "你的名字" --project "your-project" --repository "$HOME/cairn" --skills-dir "/path/to/skills"
```

不传目标参数时，和早期版本一样安装到 Codex。

安装器会：

1. 用 `template/` 创建本地的 Cairn 仓库；
2. 写入 `~/.cairn/config.json`；
3. 把 Skill 安装到每个目标，Codex 目标还会安装 `agents/openai.yaml`。

它不会覆盖非空仓库或已有的 Skill，并且在写入任何文件之前，会先检查所有目标。

## 限制

- **没有检索。** Agent 靠扫描文件名和标题决定读哪些决定，没有搜索索引、向量或排序。
- **不会学习。** 纠正会追加到 `protocol/benchmark/feedback.md`，但没有任何东西读取它来改变之后的行为。
- **没有校验。** 没有工具检查决定文件的 frontmatter、引用和历史链是否完整。

## 路线图

以下尚未实现，列出来是为了让你知道缺什么：

- 为决定文件提供 `validate` 命令。[Cairn Lite](https://github.com/alexliu072903-bit/cairn-lite) 已经为它自己的格式提供了。
- 一个小索引，让 Agent 不必扫描全部标题就能找到决定。
- 把重复出现的纠正，整理成经过审核的规则。

## 可选：每 30 分钟的 Git 同步

生成的 Cairn 仓库包含一个可选的 macOS LaunchAgent。它每 30 分钟提交本地改动、变基到远端分支并推送。遇到冲突会停止同步，并保留本地提交，等你自己处理。

先创建一个**私有**的 GitHub 仓库，并把生成的 Cairn 仓库推上去：

```bash
cd "$HOME/cairn"
git init -b main
git add .
git commit -m "init: create Cairn context"
gh repo create YOUR_ACCOUNT/cairn --private --source . --remote origin --push
```

然后由你自己启用自动同步：

```bash
bash "$HOME/cairn/scripts/setup-autosync.sh"
```

Skill 安装器不会启用自动同步。GitHub CLI 可用时，如果目标仓库是公开的，设置会拒绝同步。

## 仓库结构

```text
~/cairn/
├── AGENTS.md
├── CLAUDE.md              引入 AGENTS.md
├── protocol/
│   ├── README.md
│   └── benchmark/
│       ├── feedback.md
│       └── cases.yaml
├── scripts/
│   ├── setup-autosync.sh
│   └── sync.sh
└── projects/
    └── your-project/
        ├── README.md
        ├── state.md
        └── decisions/
```

## 该用哪个项目？

| 项目 | 上下文放在哪里 | 适合什么时候用 |
| --- | --- | --- |
| **Cairn Context**（本项目） | 你自己拥有的独立仓库，可服务一个或多个项目 | 希望决定留在项目仓库之外，并由 Agent 判断何时读取或记录 |
| [Cairn Lite](https://github.com/alexliu072903-bit/cairn-lite) | 项目内部，用普通 Markdown 加一个 CLI | 希望知识跟着仓库走，并需要 `validate` 和跨 Agent 测试 |
| [Shared Project Context](https://github.com/alexliu072903-bit/shared-project-context) | 一个跟踪目标和证据的工作区，覆盖多个人和 Agent | 需要让多个参与者与有人设定的目标保持一致 |

## 隐私边界

不要为了共享 Skill，就让多个人使用同一个个人 Cairn 仓库。共享这个公开的 Skill，各自的上下文仓库保持私有。只有确实要让团队阅读的决定，才单独建一个团队仓库。

## License

MIT
