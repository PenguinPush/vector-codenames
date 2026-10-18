/* Standard tab keyboard behavior without changing game or experiment state. */
for (const group of document.querySelectorAll('[role="tablist"]')) {
    const tabs = [...group.querySelectorAll('[role="tab"]')];
    const sync = () => tabs.forEach(tab => { tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1; });
    for (const tab of tabs) {
        tab.addEventListener('click', sync);
        tab.addEventListener('keydown', event => {
            const index = tabs.indexOf(tab);
            const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
                : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
                : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
            if (next === null) return;
            event.preventDefault(); tabs[next].focus(); tabs[next].click(); sync();
        });
    }
    new MutationObserver(sync).observe(group, {subtree:true, attributes:true, attributeFilter:['aria-selected']});
    sync();
}
