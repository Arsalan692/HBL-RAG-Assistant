import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "@/App";
import StatesPage from "@/StatesPage";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import "@/styles/index.css";

/**
 * Two surfaces, one bundle: the product, and the interaction-states reference
 * at #/states used for design handoff. A router would be overkill for this.
 */
function Root() {
  const [hash, setHash] = useState(() => window.location.hash);

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return hash === "#/states" ? <StatesPage /> : <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SettingsProvider>
      <Root />
    </SettingsProvider>
  </StrictMode>,
);
