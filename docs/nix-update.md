# 为什么不用 nix-update

结论：magpie 的版本和 hash 只由 `./update.py` 改，不要换成 nix-update。
两条原因都是看 1.16.0 源码得出的（源码在 `/nix/store/*-nix-update-1.16.0/lib/python3*/site-packages/nix_update/`）。

## 1. 上游只打 tag，不发 release

```console
$ gh release list --repo yetone/magpie --limit 5
（空）
$ git ls-remote --tags https://github.com/yetone/magpie | tail -2
v0.1.765
v0.1.766
```

nix-update 只认 release：

- 默认走 `fetch_github_versions_from_feed()`，读
  `https://github.com/{owner}/{repo}/releases.atom`（`version/github.py:141`），
  那行上面还留着 `# TODO fallback to tags?`；
- `--use-github-releases` 换成 `/releases` API（`options.py:159`→
  `fetch_github_versions_from_releases()`），也是 release。

`options.py` 里没有任何"读 tag"的开关。所以在这里它看不到新版本。

## 2. 就算有 release，`rev` 也不会被改

`update.py:44-49` 只在 `package.new_version.rev` 非空时才替换 rev 行：

```python
if old_rev_tag is not None and package.new_version.rev:
    modified_line = modified_line.replace(old_rev_tag, package.new_version.rev)
```

而这个字段只有 branch/snapshot 模式才有值（`version/github.py:215`：
`Version(f"{version}-unstable-{date}", rev=commit)`）。走 release/tag 时它是
`None` → 只有版本号从 `"0.1.753"` 换成 `"0.1.766"`，`rev` 仍指向旧 commit，
接着 prefetch 用的 fetcher 参数也是旧的，算出来的 hash 与原来相同。

结果是"更新成功"但源码根本没换：**静默错误，不会构建失败**。这比直接失败更麻烦。

另外 `old_rev_tag.endswith(package.old_version)`（`update.py:85`）决定
`version_prefix`，我们的 rev 是 40 位 sha、不以版本号结尾，所以前缀推导也是空的。

## 不是它的问题

`vendorHash` 那块 nix-update 是支持的（`dependency_hashes.py`）。别把上面两点和它
混为一谈——早先 AGENTS.md 里写成"对 vendorHash 的改写未经验证"是错的，已更正。

## 什么时候可以改用 nix-update

上游开始发 GitHub release，并且包改用 `tag = "v${version}"` 而不是钉 `rev`
（即不再需要 tag→commit 的解析）。届时 `update.py` 的 `git ls-remote` 那段才多余。
