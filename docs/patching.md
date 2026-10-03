# 补丁为什么用 patch 文件

结论：`patches = [ ./no-self-desktop-file.patch ]`，不要在 `postPatch` 里用 sed 或
`substituteInPlace` 改上游源码。理由是**失效时响不响**。

## patch 文件：打不上就是构建失败

`patchPhase` 的实现（`pkgs/stdenv/generic/setup.sh:1376-1409`）：

```bash
for i in "${patchesArray[@]}"; do
    $uncompress < "$i" 2>&1 | patch "${flagsArray[@]}"   # 默认 -p1
done
```

`setup.sh:4-5` 有 `set -eu` 和 `set -o pipefail`，所以 `patch` 非零退出（hunk 对不上）
会直接终止构建。上游一改那段代码，构建就红，不会带着旧行为继续。

## sed / substituteInPlace：不响

- `sed -i` 的表达式匹配不到时**退出码是 0**，文件原样不动。
- `substituteInPlace --replace` 更隐蔽：`--replace` 是 deprecated 别名，按
  `--replace-warn` 处理（`setup.sh:1030-1047`）——pattern 没匹配到只往 stderr 打一行
  WARNING，然后继续。要响得用 `--replace-fail`，或者自己补 grep 断言。

早先的版本就是 sed + 两道 grep 断言；换成 patch 文件后那两道断言可以删掉。

## 附带确认的两件事

- `buildGoModule` 会把 `patches` / `postPatch` 一并传给 vendor 那个 derivation
  （`pkgs/build-support/go/module.nix:109-111`）。我们的补丁只改 `.go` 文件、不动
  `go.mod`/`go.sum`，所以 `vendorHash` 不受影响。
- patch 文件里的注释用英文（它是打在上游代码上的，可能往上反映）。
