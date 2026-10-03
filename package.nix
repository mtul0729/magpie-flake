# magpie —— 把每个 AI 编程 agent 的模型设置收进一个下拉里（菜单栏 / TUI / 本地网关）。
#
# 升级走同目录的 ./update.py（CLI 契约与不变式写在该脚本头部）：上游每几个提交
# 就打一个 tag，version / rev / src hash / vendorHash 四个字段一起动。
#
# 走源码构建而非官方 install.sh：那个脚本下载的是 FHS 下的预编译二进制，
# 在 NixOS 上既没有 /lib64/ld-linux-x86-64.so.2，也探测不到 WebKitGTK。
#
# Linux 上的桌面窗口走 Wails v3 + cgo。Wails 在 Linux 的默认后端是 GTK 4 /
# WebKitGTK 6；Makefile 里的 gtk3 tag 只是给老发行版的兼容开关，这里不加它：
# GTK 3 路径在这台机器的 COSMIC Wayland 会话下整个窗口画不出来——只剩顶部一条
# UI，其余全黑，WEBKIT_DISABLE_DMABUF_RENDERER=1 和
# WEBKIT_DISABLE_COMPOSITING_MODE=1 都救不回来，而 GTK 4 / WebKitGTK 6 走原生
# Wayland 完全正常（截图核对过）。nogui 版本则是纯 Go、无 cgo。
#
# 之所以坚持"不依赖环境变量"，是因为最早那版 wrapper（--set GDK_BACKEND x11）
# 站不住：magpie 首次运行会自己往 ~/.local/share/applications/magpie.desktop
# 写一份桌面文件（internal/gui/scheme_linux.go，注册 magpie:// 导入链接），
# Exec 用的是 os.Executable()——wrapper exec 掉之后它拿到的是真实二进制，
# 于是绕过 wrapper；XDG 里用户目录优先级高于系统目录，启动器用的正是那一份。
#
# 上游 Linux 只给一个裸二进制，没有 .desktop（只有 macOS 的 Info.plist 和
# Windows 的 winres），桌面文件由安装器或首次运行时写。包里这份是给启动器先
# 备上的，图标取 build/windows 里的 256px PNG。
{
  lib,
  buildGoModule,
  fetchFromGitHub,
  makeDesktopItem,
  pkg-config,
  gtk4,
  webkitgtk_6_0,
}:

let
  desktopItem = makeDesktopItem {
    name = "magpie";
    desktopName = "magpie";
    comment = "Every agent's model, one place";
    exec = "magpie %U";
    icon = "magpie";
    categories = [
      "Development"
      "Utility"
    ];
    startupWMClass = "magpie";
    terminal = false;
  };
in
buildGoModule rec {
  pname = "magpie";
  version = "0.1.739";

  src = fetchFromGitHub {
    owner = "yetone";
    repo = "magpie";
    rev = "ae6b4c9335e83b04a3597d7e6e3c233abe11d4db";
    hash = "sha256-/oUP1xWGmJOwp4rYeTgQoP09B1pqh+SneHqgny01PZ8=";
  };

  vendorHash = "sha256-XEaHZVw3co0yUV6fLUlSkvg9LlroKFj2B2sjMW1e6BU=";

  # go mod vendor 拉大 zip 时连接会被中途重置（unexpected EOF），换国内镜像。
  # 镜像仍可能把 zip 请求送回上游，所以这不保证一次成功——重跑通常就好，
  # ./update.py 里对这一步做了重试。go.sum 已有全部依赖，GOSUMDB 不参与校验。
  # 换镜像的原因是打包机所在的网络，不是上游要求：能直连 proxy.golang.org 的
  # 环境可以去掉这一整段 overrideModAttrs。
  overrideModAttrs = _: {
    GOPROXY = "https://goproxy.cn";
    GOSUMDB = "off";
  };

  # production 只是 Makefile 里的惯例 tag，源码里没有任何 //go:build production，
  # 带上它是为了和上游发布产物保持一致。不加 gtk3，见文件头。
  tags = [ "production" ];

  ldflags = [
    "-s"
    "-w"
    "-X main.version=v${version}"
  ];

  nativeBuildInputs = [
    pkg-config
  ];

  buildInputs = [
    gtk4
    webkitgtk_6_0
  ];

  postInstall = ''
    install -Dm644 build/windows/icon-256.png $out/share/icons/hicolor/256x256/apps/magpie.png
    install -Dm644 ${desktopItem}/share/applications/magpie.desktop \
      $out/share/applications/magpie.desktop
  '';

  # 上游 release/CI 已验证过这个 tag，包层不重复跑完整测试。
  doCheck = false;

  meta = {
    description = "Every agent's model, one place";
    homepage = "https://usemagpie.ai";
    license = lib.licenses.mit;
    mainProgram = "magpie";
    platforms = lib.platforms.linux;
  };
}
