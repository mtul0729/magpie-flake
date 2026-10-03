# desktop 文件这整件事

## 它自己会写一份

`internal/gui/scheme_linux.go` 的 `registerScheme()` 往
`$XDG_DATA_HOME/applications/magpie.desktop`（默认
`~/.local/share/applications/magpie.desktop`）写：

```ini
[Desktop Entry]
Type=Application
Name=magpie
Comment=Every agent's model. One place.
Exec=<os.Executable()> %u     ← store 绝对路径
Icon=magpie
Categories=Development;Utility;
MimeType=x-scheme-handler/magpie;
Terminal=false
```

写之前有幂等判断（同一文件 `scheme_linux.go:36`）：已存在且包含
`Exec=<当前 exe> %u` 和那个 MimeType 就跳过。写完还跑两条命令：

```go
proc.Command("update-desktop-database", dir).Run()
proc.Command("xdg-mime", "default", "magpie.desktop", "x-scheme-handler/magpie").Run()
```

## 钉绝对路径为什么会自锁

XDG 里用户目录（`~/.local/share/applications`）优先于系统目录
（`XDG_DATA_DIRS` 里的 `/run/current-system/sw/share`、
`~/.nix-profile/share` 等）。于是：

1. 某次运行写下 `Exec=/nix/store/621qd3ymm…-magpie-0.1.639/bin/magpie`；
2. 之后无论升多少版，启动器用的都是这条旧路径（那个 store path 还在）；
3. 旧版本启动后又把自己写回去，文件永远不更新。

实测：2026-10-02 写下的 0.1.639，到 10-03 上游已经 0.1.766，启动器拉的仍是它。

## 我们怎么处理

- **禁用它写文件**：`no-self-desktop-file.patch` 让 `registerScheme()` 直接
  `return nil`（后面的代码留着，Go 不管不可达代码，且留着 import 才是被用到的）。
  那两条 `update-desktop-database` / `xdg-mime default` 也一并消失。
- **桌面文件只留包里那份**：`package.nix` 里 `makeDesktopItem`，`Exec = "magpie %U"`，
  PATH 查找，不含版本。
- **声明类型保留，设默认不做**：保留 `MimeType=x-scheme-handler/magpie`
  （这是"我能处理"，合理）；**不**用 `xdg.mimeApps.defaultApplications` 之类把
  "设为默认"补回来——替用户决定默认应用正是要去掉的那部分。

## 存量清理

禁用了就不会再生成，但**已存在的那份要手动删一次**
（`~/.local/share/applications/magpie.desktop`）。2026-10-03 已删；本机
`~/.config/mimeapps.list` 里那条 `x-scheme-handler/magpie=magpie.desktop`
按用户要求保留未动（它按 desktop 文件 ID 记，不记路径，所以不会指向旧版本）。

## 参考：XDG 查找顺序

`XDG_DATA_DIRS` 在本机是
`/nix/store/…-desktops/share : ~/.local/share/flatpak/exports/share : … :
~/.nix-profile/share : … : /etc/profiles/per-user/myul/share : … :
/run/current-system/sw/share : …`，另有 `~/.local/share` 永远优先。
