---
name: evoflow-chat-smoke
description: >-
  自动验证 EvoFlow Web 聊天端到端流程：启动或复用本地 Vite、使用运行时提供的组织用户名/密码登录、进入聊天、新建会话、发送用户明确指定的验证消息，并检查用户消息显示、AI 运行结束和 assistant 回复。用户要求自动登录、聊天冒烟、验证 EvoPanel 聊天链路、重现登录后发送消息时使用。不会把凭据写入文件；只有显式运行发送测试用例才会创建会话并发送消息。
---

# EvoFlow Chat Smoke

用固定 Playwright E2E 测试重复完成 Web 登录与聊天验证。凭据只通过运行时环境变量读取，严禁写入此 skill、脚本、shell 历史或报告。

## 前置条件

- 在 `evopanel/` 安装好的项目依赖（包含 `@playwright/test`）。
- EvoFlow Gateway 可通过 Vite 代理访问，默认 `http://127.0.0.1:8070`。
- 一组有权登录本地目标组织的用户名和密码。
- `EVOFLOW_E2E_PASSWORD` 用于组织账号登录；若环境还要求额外的面板访问密码，需另行完成该门禁，不能混用两类密码。

## 执行

PowerShell：

```powershell
$credential = Get-Credential -UserName 'admin' -Message 'EvoFlow 组织登录'
$env:EVOFLOW_E2E_USERNAME = $credential.UserName
$env:EVOFLOW_E2E_PASSWORD = $credential.GetNetworkCredential().Password
$env:EVOFLOW_E2E_MESSAGE = '验证消息：请只回复“收到”，用于确认聊天发送链路正常。'
npm run test:e2e -- e2e/chat-login-send.spec.js --grep 'explicitly requested'
Remove-Variable credential
Remove-Item Env:EVOFLOW_E2E_PASSWORD
```

凭据只保存在当前 PowerShell 进程环境，测试输出绝不打印密码；测试结束后立即清除环境变量。

这是会真实创建会话并发送消息的用例。只有用户明确要求发送验证消息时才运行；未获授权时不要运行该命令。`EVOFLOW_E2E_MESSAGE` 留空时，Playwright 会 skip，不会发送。

```powershell
cd evopanel
$env:EVOFLOW_E2E_BASE_URL = 'http://127.0.0.1:1421'
$env:EVOFLOW_GATEWAY_PORT = '8070'
npm run test:e2e -- e2e/chat-login-send.spec.js --grep 'explicitly requested'
```

Playwright 配置会复用运行中的 Vite 或自动启动它。需要其它服务地址时覆写 `EVOFLOW_E2E_BASE_URL` 与 `EVOFLOW_GATEWAY_URL`。使用 `$env:EVOFLOW_E2E_HEADED='1'` 可显示浏览器。

## 验收

测试必须确认：

1. 若落在登录页，填写组织用户名/密码并提交；若当前已经登录，直接继续。
2. 登录后到达 `#/chat`，聊天输入框可交互，且没有 Gateway 不可达遮罩。
3. 点击“新建对话”，确保验证消息不会污染已有会话。
4. 只发送一次 `EVOFLOW_E2E_MESSAGE`。
5. 用户消息出现在当前对话；等待运行状态结束，并确认出现 assistant 消息。
6. 收集页面错误；若包含 `fastdom_stub_default.extend is not a function`，测试失败并报告这是渲染回归。

超时/认证失败/Gateway 不可达时停止，不重试登录或重复发送。失败时使用 Playwright 保留的截图、视频及 trace 定位。不得把认证 token、密码或消息外的用户会话内容贴到报告中。

## 固定实现

脚本：`evopanel/e2e/chat-login-send.spec.js`。登录选择器依据 `src/pages/login.js` 的 `#login-username`、`#login-password`、`#login-submit`；聊天 Composer 使用稳定的可访问名称和现有应用状态。不要把凭据硬编码进测试，也不要改成在旧对话里发送。
