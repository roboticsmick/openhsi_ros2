import { ExtensionContext } from "@foxglove/extension";
import { createElement } from "react";
import { createRoot } from "react-dom/client";

import { HypercubePanel } from "./HypercubePanel";

export function activate(extensionContext: ExtensionContext): void {
  extensionContext.registerPanel({
    name: "Hypercube Waterfall",
    initPanel: (context) => {
      const root = document.createElement("div");
      root.style.width = "100%";
      root.style.height = "100%";
      context.panelElement.appendChild(root);

      const reactRoot = createRoot(root);
      reactRoot.render(createElement(HypercubePanel, { context }));

      // Return cleanup function
      return () => {
        reactRoot.unmount();
      };
    },
  });
}
