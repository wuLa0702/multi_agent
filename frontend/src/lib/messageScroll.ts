/**
 * messageScroll — 消息区滚动容器共享 ref（P1-5 本地搜索跳转用）。
 * ChatMessages 持有真实容器；SearchPanel / OverviewRuler 经此跳转消息。
 * 模块级单例，避免跨组件层层透传 scrollRef。
 */

import { createRef } from "react";

/** 消息滚动容器引用（ChatMessages 挂载，SearchPanel 读取） */
export const messageScrollRef = createRef<HTMLDivElement | null>();
