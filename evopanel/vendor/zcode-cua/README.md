# @zcode/zcode-cua

API-compatible placeholder package for Computer Use. This build ships without
Computer Use: every runtime surface (Computer Use runtime, broker RPC, Helper
install/launch/verify, PiP session client, native addon loader) reports
**unavailable** and fails closed, predicates about official CUA frames are
`false`, and permission ports keep their privacy fail-closed semantics.

## Upstream / License

Vendored from [ZCode](https://github.com/zai-org/ZCode) (Z.AI Co., Ltd.).

```
Copyright 2026 Z.AI Co., Ltd
Licensed under the Apache License, Version 2.0.
```

A copy of the Apache-2.0 license text is kept in this repository at
`licenses/zcode-APACHE-2.0.txt`. The Apache-2.0 license applies only to
this `vendor/zcode-cua` directory and the other zcode-* paths listed in
the top-level `NOTICE`; it does not change EvoFlow's primary
PolyForm Noncommercial 1.0.0 license for the rest of the repository,
and it does not grant any right to use Z.AI's trademarks.