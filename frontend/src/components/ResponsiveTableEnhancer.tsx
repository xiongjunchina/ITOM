import { useEffect } from 'react';

const TABLE_SELECTOR = '.ant-table-wrapper';
const SCROLL_SELECTOR = '.ant-table-body, .ant-table-content';

type TableController = {
  wrapper: HTMLElement;
  scroll: HTMLElement;
  bottom: HTMLDivElement;
  bottomInner: HTMLDivElement;
  cleanup: () => void;
  update: () => void;
};

function findScrollElement(wrapper: HTMLElement): HTMLElement | null {
  const candidates = Array.from(wrapper.querySelectorAll<HTMLElement>(SCROLL_SELECTOR));
  return candidates.find((node) => node.scrollWidth > node.clientWidth + 1) ?? candidates[0] ?? null;
}

type ActivateTable = (wrapper: HTMLElement) => void;

function getViewportRect(wrapper: HTMLElement): DOMRect {
  const scrollParent = wrapper.closest<HTMLElement>('.app-content');
  if (scrollParent) return scrollParent.getBoundingClientRect();
  return new DOMRect(0, 0, window.innerWidth, window.innerHeight);
}

function getIntersectionArea(wrapper: HTMLElement): number {
  const rect = wrapper.getBoundingClientRect();
  const viewport = getViewportRect(wrapper);
  const left = Math.max(rect.left, viewport.left);
  const right = Math.min(rect.right, viewport.right);
  const top = Math.max(rect.top, viewport.top);
  const bottom = Math.min(rect.bottom, viewport.bottom);
  return Math.max(0, right - left) * Math.max(0, bottom - top);
}

function createController(wrapper: HTMLElement, scroll: HTMLElement, activateTable: ActivateTable): TableController {
  const bottom = document.createElement('div');
  const bottomInner = document.createElement('div');
  bottom.className = 'responsive-table__bottom-scroll';
  bottom.setAttribute('aria-label', '表格横向滚动条');
  bottom.setAttribute('aria-hidden', 'true');
  bottom.dataset.visible = 'false';
  bottomInner.setAttribute('aria-hidden', 'true');
  bottom.appendChild(bottomInner);
  // 挂到 body，避免滚动到表格末尾后受卡片/app-content 边界约束而消失。
  // 位置由 update() 根据当前表格的可视区域动态计算。
  document.body.appendChild(bottom);

  wrapper.classList.add('responsive-table--enhanced');
  const needsNativeStickyHeader = !wrapper.querySelector('.ant-table-sticky-holder');
  wrapper.classList.toggle('responsive-table--native-header', needsNativeStickyHeader);

  let syncing = false;
  const sync = (source: HTMLElement, target: HTMLElement) => {
    if (syncing) return;
    syncing = true;
    target.scrollLeft = source.scrollLeft;
    window.requestAnimationFrame(() => { syncing = false; });
  };
  const onBottomScroll = () => sync(bottom, scroll);
  const onBodyScroll = () => sync(scroll, bottom);
  bottom.addEventListener('scroll', onBottomScroll, { passive: true });
  scroll.addEventListener('scroll', onBodyScroll, { passive: true });
  const onActivate = () => activateTable(wrapper);
  wrapper.addEventListener('pointerenter', onActivate);
  wrapper.addEventListener('focusin', onActivate);
  scroll.addEventListener('scroll', onActivate, { passive: true });

  let positionFrame = 0;
  const update = () => {
    const overflow = scroll.scrollWidth > scroll.clientWidth + 1;
    bottomInner.style.width = `${Math.max(scroll.scrollWidth, scroll.clientWidth, 1)}px`;
    const rect = wrapper.getBoundingClientRect();
    const viewport = getViewportRect(wrapper);
    const viewportLeft = Math.max(0, Math.max(rect.left, viewport.left));
    const viewportRight = Math.min(window.innerWidth, Math.min(rect.right, viewport.right));
    // visible 由外层统一选择当前表格，避免多个表格同时绘制悬浮滚动条。
    // 即使表格已经滚到视口上方，只要它仍是当前活动表格，滚动条也继续保留，
    // 这样用户在页面底部仍可横向查看最后几行的隐藏列。
    const visible = overflow && bottom.dataset.active === 'true' && viewportRight > viewportLeft;
    bottom.dataset.visible = visible ? 'true' : 'false';
    bottom.setAttribute('aria-hidden', visible ? 'false' : 'true');
    if (visible) {
      bottom.style.left = `${Math.round(viewportLeft)}px`;
      bottom.style.width = `${Math.round(viewportRight - viewportLeft)}px`;
      bottom.style.bottom = `${Math.max(0, Math.round(window.innerHeight - viewport.bottom))}px`;
    }
    if (Math.abs(bottom.scrollLeft - scroll.scrollLeft) > 1) bottom.scrollLeft = scroll.scrollLeft;
  };
  const scheduleUpdate = () => {
    if (positionFrame) return;
    positionFrame = window.requestAnimationFrame(() => {
      positionFrame = 0;
      update();
    });
  };
  update();

  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(scheduleUpdate) : null;
  resizeObserver?.observe(wrapper);
  resizeObserver?.observe(scroll);
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  // app-content 是内部滚动容器，捕获阶段才能收到它的 scroll 事件。
  document.addEventListener('scroll', scheduleUpdate, true);

  return {
    wrapper,
    scroll,
    bottom,
    bottomInner,
    update,
    cleanup: () => {
      bottom.removeEventListener('scroll', onBottomScroll);
      scroll.removeEventListener('scroll', onBodyScroll);
      wrapper.removeEventListener('pointerenter', onActivate);
      wrapper.removeEventListener('focusin', onActivate);
      scroll.removeEventListener('scroll', onActivate);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', scheduleUpdate);
      window.removeEventListener('scroll', scheduleUpdate);
      document.removeEventListener('scroll', scheduleUpdate, true);
      if (positionFrame) window.cancelAnimationFrame(positionFrame);
      bottom.remove();
      wrapper.classList.remove('responsive-table--enhanced', 'responsive-table--native-header');
      wrapper.style.removeProperty('--responsive-table-sticky-offset');
    },
  };
}

/**
 * 为所有 antd 表格补齐统一的宽表交互：表格超宽时提供底部悬浮横向滚动条，
 * 表头在内容区纵向滚动时保持可见；WBS 也复用同一条底部悬浮滚动条。
 */
export default function ResponsiveTableEnhancer(): null {
  useEffect(() => {
    const controllers = new Map<HTMLElement, TableController>();
    let activeWrapper: HTMLElement | null = null;
    let frame = 0;

    const refresh = () => {
      frame = 0;
      const wrappers = Array.from(document.querySelectorAll<HTMLElement>(TABLE_SELECTOR))
        .filter((wrapper) => !wrapper.closest('.responsive-table__bottom-scroll'));
      const active = new Set(wrappers);

      // 只在确实存在横向溢出的表格之间选择活动表，避免普通窄表抢走唯一滚动条。
      const wideWrappers = wrappers.filter((wrapper) => {
        const scroll = findScrollElement(wrapper);
        return Boolean(scroll && scroll.scrollWidth > scroll.clientWidth + 1);
      });
      // 选择当前视口中占比最大的宽表；滚出视口后保留该活动表格，直到另一张宽表进入视口。
      const visibleWrapper = wideWrappers
        .map((wrapper) => ({ wrapper, area: getIntersectionArea(wrapper) }))
        .filter((entry) => entry.area > 0)
        .sort((left, right) => right.area - left.area)[0]?.wrapper;
      if (visibleWrapper) activeWrapper = visibleWrapper;
      if (activeWrapper && !active.has(activeWrapper)) activeWrapper = visibleWrapper ?? null;

      controllers.forEach((controller, wrapper) => {
        if (!active.has(wrapper) || !document.body.contains(wrapper)) {
          controller.cleanup();
          controllers.delete(wrapper);
        }
      });

      wrappers.forEach((wrapper) => {
        const scroll = findScrollElement(wrapper);
        if (!scroll) return;
        const current = controllers.get(wrapper);
        if (current && current.scroll === scroll) {
          current.bottom.dataset.active = activeWrapper === wrapper ? 'true' : 'false';
          current.bottom.dataset.visible = activeWrapper === wrapper ? 'true' : 'false';
          current.update();
          return;
        }
        current?.cleanup();
        controllers.set(wrapper, createController(wrapper, scroll, (nextWrapper) => {
          activeWrapper = nextWrapper;
          scheduleRefresh();
        }));
      });

      controllers.forEach((controller, wrapper) => {
        controller.bottom.dataset.active = activeWrapper === wrapper ? 'true' : 'false';
        controller.bottom.dataset.visible = activeWrapper === wrapper ? 'true' : 'false';
        controller.update();
      });
    };
    const scheduleRefresh = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(refresh);
    };

    refresh();
    const observer = new MutationObserver(scheduleRefresh);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', scheduleRefresh);
    document.addEventListener('scroll', scheduleRefresh, true);
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', scheduleRefresh);
      document.removeEventListener('scroll', scheduleRefresh, true);
      controllers.forEach((controller) => controller.cleanup());
      controllers.clear();
    };
  }, []);

  return null;
}
