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
  // 挂到 body，避免滚动到表格末尾后受卡片或 app-content 边界约束而消失。
  // 它本身是浏览器原生滚动容器，不依赖 rc-table 的模拟拖拽事件。
  document.body.appendChild(bottom);

  wrapper.classList.add('responsive-table--enhanced');

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
    // 仅显示当前可视区域中的活动宽表，防止多张表同时生成滚动条。
    const visible = overflow && bottom.dataset.active === 'true' && viewportRight > viewportLeft;
    bottom.dataset.visible = visible ? 'true' : 'false';
    bottom.setAttribute('aria-hidden', visible ? 'false' : 'true');
    // 只有原生悬浮条已完成测量且实际可用时，才隐藏表内重复滚动条。
    // 若 MutationObserver、尺寸测量或浏览器环境异常，表内原生条仍是可靠入口。
    wrapper.classList.toggle('responsive-table--floating-scroll-active', visible);
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
      wrapper.classList.remove('responsive-table--enhanced', 'responsive-table--floating-scroll-active');
    },
  };
}

/**
 * 为全部 Ant Design 宽表提供一个可由浏览器原生拖拽的底部横向滚动条。
 * 只在确有横向溢出时接管；表格自身的原生滚动条始终作为兜底。
 */
export default function ResponsiveTableEnhancer(): null {
  useEffect(() => {
    const controllers = new Map<HTMLElement, TableController>();
    let activeWrapper: HTMLElement | null = null;
    let frame = 0;

    const refresh = () => {
      frame = 0;
      const wrappers = Array.from(document.querySelectorAll<HTMLElement>(TABLE_SELECTOR))
        // StickyTable 自己维护唯一底部原生滚动条；全局增强器不得再为它创建第二条。
        .filter((wrapper) => !wrapper.closest('.responsive-table__bottom-scroll') && !wrapper.closest('.sticky-table'));
      const active = new Set(wrappers);

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
        if (current?.scroll === scroll) return;
        current?.cleanup();
        controllers.set(wrapper, createController(wrapper, scroll, (nextWrapper) => {
          activeWrapper = nextWrapper;
          scheduleRefresh();
        }));
      });

      const wideWrappers = wrappers.filter((wrapper) => {
        const controller = controllers.get(wrapper);
        return Boolean(controller && controller.scroll.scrollWidth > controller.scroll.clientWidth + 1);
      });
      const visibleWrapper = wideWrappers
        .map((wrapper) => ({ wrapper, area: getIntersectionArea(wrapper) }))
        .filter((entry) => entry.area > 0)
        .sort((left, right) => right.area - left.area)[0]?.wrapper;
      if (visibleWrapper) activeWrapper = visibleWrapper;
      if (!activeWrapper || !active.has(activeWrapper) || !wideWrappers.includes(activeWrapper)) {
        activeWrapper = visibleWrapper ?? wideWrappers[0] ?? null;
      }

      controllers.forEach((controller, wrapper) => {
        controller.bottom.dataset.active = activeWrapper === wrapper ? 'true' : 'false';
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
