# AGENTS.md

把 [yetone/magpie](https://github.com/yetone/magpie) 打成独立 Nix 包的 flake：
源码构建（`buildGoModule` + GTK 4 / WebKitGTK 6），跟上游最新 tag，GitHub Actions
每小时查一次新版、每周刷一次 `flake.lock`，构建产物进 `mtul` cachix。

## 仓库结构

- `flake.nix` — 只有 `nixpkgs`（`nixos-unstable`）一个 input；输出
  `packages.<system>.magpie` / `default` 和 `overlays.default`；`nixConfig`
  声明 mtul cachix。`systems` 只有 linux 两项：桌面窗口是 Wails v3 + cgo，
  Linux 上只走 GTK/WebKitGTK。
- `package.nix` — 包本体。头部注释记了几个结论的来由（为什么源码构建、为什么
  不加 `gtk3` tag、为什么不能靠 wrapper 设环境变量），改之前先看。
- `no-self-desktop-file.patch` — 关掉它自己写 desktop 文件的行为，理由见下。
- `update.py` — 唯一能改版本和 hash 的入口，契约写在其 docstring 里。
- `.github/actions/setup/action.yml` — 装 nix + cachix daemon（复合 action）。
- `.github/workflows/` — `update-package.yml`（每小时）、`update-flake-lock.yml`
  （每周）、`build.yml`（push/PR）。

## 约定

- **跟最新 tag，不是 release。** 上游几个提交就打一个 tag（已有 700+），一天能出
  好几个，所以更新频率定的是每小时。
- **四个字段一起动**：`version`、`rev`、`src hash`、`vendorHash`。只有
  `./update.py` 可以改，CI 也是调它；不要手改其中一两个。
- **不用 nix-update**（1.16.0 实测源码），两个具体原因：
  1. 上游只打 tag、不发 release（`gh release list --repo yetone/magpie` 是空的），
     而 nix-update 只认 release：默认读 `releases.atom`
     （`version/github.py:141`，旁边还留着 `# TODO fallback to tags?`），
     `--use-github-releases` 也只是换成 `/releases` API，没有读 tag 的开关。
  2. 就算有 release，它也不会动 `rev`：`update.py:44-49` 只在
     `new_version.rev` 非空时替换 rev 行，而那个字段只有 branch/snapshot 模式才
     有值（`github.py:215`）。走 tag 时只把版本号换了，`rev` 仍指向旧 commit，
     prefetch 拿到的 hash 也和旧的一样——"更新成功"但源码没变，是静默错误。
  它处理 `vendorHash` 那部分本身没问题，别把这两件事混为一谈。
- **补丁用 patch 文件，不用 sed。** `patchPhase` 是 `patch -p1`
  （`pkgs/stdenv/generic/setup.sh:1385`）配 `set -e` + `pipefail`，打不上就是构建
  失败；sed 匹配不到退出码仍是 0，`substituteInPlace --replace` 也只打 WARNING
  不失败——要响就得自己补断言，没必要。
- `buildGoModule` 会把 `patches` / `postPatch` 一起传给 vendor 那个 derivation
  （`pkgs/build-support/go/module.nix:109-111`）；只改 `.go` 文件、不动
  go.mod/go.sum，`vendorHash` 不受影响。
- **不写 `GOPROXY` 镜像。** 构建和升版都在 CI 上跑，默认 `proxy.golang.org` 就够；
  写死 `goproxy.cn` 只是当初打包机网络的问题。本地跑 `./update.py` 若被中途重置，
  重跑即可（脚本自带 3 次重试）。
- **desktop 文件只留包里这份。** 上游会在
  `~/.local/share/applications/magpie.desktop` 写一份，把 `Exec` 钉成
  `os.Executable()` 的 store 绝对路径；XDG 用户目录优先于系统目录，于是升版后启动
  器一直拉起旧版本，旧版本又把自己写回去（实测卡在 0.1.639 十几天，116 个 tag）。
  所以整段 `registerScheme` 被 patch 成直接返回。
- **声明类型可以，设默认不行。** 包里这份保留
  `MimeType=x-scheme-handler/magpie`（"我能处理"），但上游那个
  `xdg-mime default` 把自己写进用户 `mimeapps.list` 的动作刻意不补——不要用
  `xdg.mimeApps.defaultApplications` 之类的配置把它补回来。

## 构建与验证

```bash
nix flake check --accept-flake-config   # 只求值，快
nix eval --raw .#magpie.name            # 确认版本
./update.py --check                     # 只比对 version/rev，不下载不构建（退出码 1 = 有新版）
```

完整构建交给 CI（本机拉大 zip 会被中途重置）；要在本地构建就
`nix build .#magpie --accept-flake-config -L`，失败先重跑一次再判断。

确认 cachix 上有某个产物（URL 是裸 store hash，不带包名）：

```bash
curl -s -o /dev/null -w "%{http_code}" https://mtul.cachix.org/<hash>.narinfo
```

## 版本控制

- 用 `jj`（与 git colocated）；`jj st`、`jj describe -m ...`、`jj git push`。
  GitHub：`mtul0729/magpie-flake`，默认分支 `main`。
- **提交前先 `jj git fetch` 再 `jj rebase -r @ -d main@origin`**：更新 workflow 是
  直推 main 的，本地几乎总是落后。

## CI 注意

- cachix 靠 daemon 自动推送（`useDaemon: true`），workflow 里没有显式 push；别改成
  手动 push，也别设 `skipAddingSubstituter`（只推不拉会让每次 CI 重编）。没配
  `CACHIX_AUTH_TOKEN` 时该步骤自动跳过。
- `update-package.yml` 的顺序是 `--check`（只 `git ls-remote`，很便宜）→ bump →
  `nix build` → 直推 main。构建在推送之前，坏 tag 会停在 CI 而不是落到 main。
- 它不开 PR：这个仓库的 bot 走直推，别照别的仓库改成 PR + auto-merge。
- GitHub 的 schedule 在负载高时会延后甚至丢跑，"每小时"是上限频率不是保证。
- 本地 nix 会缓存 flake-ref 约 1 小时：推送后用 `github:` 引用验证要加 `--refresh`，
  否则可能拿到旧 commit。
