# AGENTS.md

把 [yetone/magpie](https://github.com/yetone/magpie) 打成独立 Nix 包的 flake：
源码构建（`buildGoModule` + GTK 4 / WebKitGTK 6），跟上游最新 tag，GitHub Actions
每小时查一次新版、每周刷一次 `flake.lock`，构建产物进 `mtul` cachix。

理由类的东西不写在这里，见 [`docs/`](docs/README.md)。

## 仓库结构

- `flake.nix` — 只有 `nixpkgs`（`nixos-unstable`）一个 input；输出
  `packages.<system>.magpie` / `default` 和 `overlays.default`；`nixConfig` 声明
  mtul cachix。`systems` 只有 linux 两项：桌面窗口是 Wails v3 + cgo，Linux 上只走
  GTK/WebKitGTK。
- `package.nix` — 包本体。头部注释记了几个结论的来由（为什么源码构建、为什么不加
  `gtk3` tag、为什么不能靠 wrapper 设环境变量），改之前先看。
- `no-self-desktop-file.patch` — 关掉它自己写 desktop 文件的行为，见
  [docs/desktop-file.md](docs/desktop-file.md)。
- `update.py` — 唯一能改版本和 hash 的入口，CLI 契约与不变式写在其 docstring 里。
- `.github/actions/setup/action.yml` — 装 nix + cachix daemon（复合 action）。
- `.github/workflows/` — `update-package.yml`（每小时）、`update-flake-lock.yml`
  （每周）、`build.yml`（push/PR）。

## 约定

- **跟最新 tag，不是 release。** 上游几个提交就打一个 tag（已有 700+），一天能出
  好几个，所以更新频率定的是每小时。
- **四个字段一起动**：`version`、`rev`、`src hash`、`vendorHash`。只有
  `./update.py` 可以改，CI 也是调它；不要手改其中一两个。
- **不用 nix-update。** 原因见 [docs/nix-update.md](docs/nix-update.md)：上游不发
  release，且它不会动 `rev`，会留下"改了版本号没改源码"的静默错误。
- **补丁用 patch 文件，不用 sed / substituteInPlace。** 失效要是构建失败而不是静默，
  见 [docs/patching.md](docs/patching.md)。
- **不写 `GOPROXY` 镜像。** 构建和升版都在 CI 上跑，默认 `proxy.golang.org` 就够。
  本地跑 `./update.py` 若被中途重置，重跑即可（脚本自带 3 次重试）。
- **desktop 文件只留包里这份**，声明 `MimeType` 但不设默认应用——细节和判断见
  [docs/desktop-file.md](docs/desktop-file.md)。

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
