# Cairn Context

[English](README.md)

一个轻量的 Codex Skill，用来把需要长期保留的项目决策存入你自己拥有并控制的仓库。

这个公开仓库只包含可复用的 Skill 和仓库模板。你的身份、项目 Context 和决策会保存在安装器生成的另一个本地或私有仓库中。

Skill 指示 Agent 做到以下行为：

- 只读取与当前任务相关的决策（依赖 Agent 自己的判断——目前没有程序化检索）；
- 区分明确决策、倾向、问题和临时尝试；
- 存在歧义时只请求一次确认；
- 通过 `supersedes` 链保留决策的修改、撤销和历史关系；
- 把用户纠正记录到反馈日志。

这些是行为指令，不是强制保证。实际效果取决于 Agent 模型的指令遵从质量。

## 当前限制

- **没有检索。** Agent 通过扫描文件名和标题自行判断读哪些决策文件。没有搜索索引、向量嵌入或程序化的相关性排序。
- **没有学习。** 用户纠正会追加到 `protocol/benchmark/feedback.md`，但没有任何机制会读取这个日志来改变未来的行为。反馈机制目前只是记录，不是闭环。
- **没有校验。** 没有工具检查决策文件的 frontmatter 是否正确、引用是否有效、历史链是否完整。
- **仅适配 Codex。** 安装器写入 `~/.codex/skills/`。在其他 Agent 框架（Claude Code、Cursor 等）中使用需要手动适配。

## 安装

克隆这个仓库，然后运行：

```bash
bash install.sh \
  --identity "你的名字" \
  --project "your-project" \
  --repository "$HOME/cairn"
```

安装器会：

1. 使用 `template/` 创建一个本地 Cairn 仓库；
2. 写入 `~/.cairn/config.json`；
3. 把 Skill 安装到 `~/.codex/skills/cairn-context`。

如果目标仓库不是空目录，或者 Skill 已经安装，安装器会拒绝覆盖。

## 可选的 30 分钟 Git 同步

生成的 Cairn 仓库包含一个可选的 macOS LaunchAgent。启用后，它会每 30 分钟提交本地修改、基于远端分支执行 rebase，然后推送。发生冲突时，同步会停止，并保留本地 Commit，等待手动解决。

首先创建一个 **private** GitHub 仓库，并推送生成的 Cairn 仓库：

```bash
cd "$HOME/cairn"
git init -b main
git add .
git commit -m "init: create Cairn context"
gh repo create YOUR_ACCOUNT/cairn --private --source . --remote origin --push
```

然后明确启用自动同步：

```bash
bash "$HOME/cairn/scripts/setup-autosync.sh"
```

Skill 安装器绝不会自动开启同步。如果本机可以使用 GitHub CLI，而远端仓库被识别为 public，自动同步设置会拒绝继续。

## 仓库结构

```text
~/cairn/
├── AGENTS.md
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

## Agent 集成

`agents/` 目录包含 Agent 框架配置：

- `agents/openai.yaml` — OpenAI Codex 集成。

## 隐私边界

不要为了共享 Skill，让多人共同使用一个个人 Cairn 仓库。应该共享这个公开 Skill，并让每个人分别保管自己的私有 Context 仓库。只有在决策本来就需要由团队共同读取时，才创建独立的团队仓库。

## License

MIT
