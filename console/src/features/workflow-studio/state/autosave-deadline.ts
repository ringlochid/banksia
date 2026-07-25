const AUTOSAVE_DELAY_MS = 500;

type DeadlineClaim = () => boolean;
type DeadlineDelivery = (claim: DeadlineClaim) => Promise<void>;

export class AutosaveDeadline {
    private dueAt: number | null = null;
    private isDeliveryQueued = false;
    private timer: ReturnType<typeof setTimeout> | null = null;

    public constructor(
        private readonly deliver: DeadlineDelivery,
        private readonly now: () => number = Date.now,
    ) {}

    public recordEdit(): void {
        this.dueAt = this.now() + AUTOSAVE_DELAY_MS;
        this.arm();
    }

    public clear(): void {
        this.dueAt = null;
        if (this.timer !== null) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    private arm(): void {
        if (
            this.dueAt === null ||
            this.isDeliveryQueued ||
            this.timer !== null
        ) {
            return;
        }
        const delay = Math.max(0, this.dueAt - this.now());
        this.timer = setTimeout(() => {
            this.timer = null;
            this.queueDelivery();
        }, delay);
    }

    private queueDelivery(): void {
        if (this.dueAt === null || this.isDeliveryQueued) {
            return;
        }
        this.isDeliveryQueued = true;
        void this.deliver(this.claimDue)
            .catch(() => undefined)
            .finally(() => {
                this.isDeliveryQueued = false;
                this.arm();
            });
    }

    private claimDue = (): boolean => {
        if (this.dueAt === null) {
            return false;
        }
        if (this.now() < this.dueAt) {
            return false;
        }
        this.dueAt = null;
        return true;
    };
}
