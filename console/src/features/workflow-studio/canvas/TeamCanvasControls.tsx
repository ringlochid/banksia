import { Maximize2, WandSparkles } from "lucide-react";

import { Button } from "../../../components/ui";

export interface TeamCanvasControlsProps {
    readonly onFit: () => void;
    readonly onTidy: () => void;
}

export function TeamCanvasControls({ onFit, onTidy }: TeamCanvasControlsProps) {
    return (
        <div aria-label="Team canvas controls" className="team-canvas-controls">
            <Button onClick={onTidy} tone="secondary">
                <WandSparkles aria-hidden="true" size={16} />
                Tidy team
            </Button>
            <Button onClick={onFit} tone="secondary">
                <Maximize2 aria-hidden="true" size={16} />
                Fit team
            </Button>
        </div>
    );
}
