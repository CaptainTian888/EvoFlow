// 交互调整：表格本身已经能在消息流里完整浏览，再保留 fullscreen 入口会把阅读路径打断。
// 这里统一关闭表格放大，只保留复制/导出等轻量操作，消息正文和推理面板共用同一份配置。
// Markdown tables are content inside a message. Their actions must not be
// rendered as ordinary message-body content or split the reading flow.
export const STREAMDOWN_CONTROLS = {
  table: false,
} as const;
