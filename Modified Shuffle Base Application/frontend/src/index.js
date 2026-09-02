import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppContext } from "./context/ContextApi";
import { CookiesProvider } from "react-cookie";

const rootElement = document.getElementById("root");
const root = createRoot(rootElement);
root.render(
  <React.Fragment>
    <CookiesProvider>
      <AppContext>
        <App />
      </AppContext>
    </CookiesProvider>
  </React.Fragment>
);