chrome.action.onClicked.addListener((tab) => {
  if (!tab.id || !tab.url?.startsWith("https://meet.google.com/")) return;
  void chrome.tabs.create({url: chrome.runtime.getURL(`capture.html?tab=${tab.id}`)});
});
