declare const chrome: {
  action: {onClicked: {addListener(callback: (tab: {id?: number; url?: string}) => void): void}};
  tabs: {
    create(options: {url: string}): Promise<unknown>;
    getCurrent(): Promise<{id?: number}>;
  };
  runtime: {getURL(path: string): string};
  tabCapture: {getMediaStreamId(options: {targetTabId: number; consumerTabId: number}): Promise<string>};
};
