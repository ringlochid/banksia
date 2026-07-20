import { setConsoleConfig } from "../../src/app/config";

import { TEST_API_BASE_URL } from "./console-api";

export function installTestConsoleConfig(): void {
    setConsoleConfig({ apiBaseUrl: TEST_API_BASE_URL });
}
