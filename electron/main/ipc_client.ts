"""
Electron IPC Client — ZeroMQ DEALER + SUB for communicating with the Python backend.

This file runs in the Electron MAIN process(Node.js).
It requires: npm install zeromq(v6 +)
"""

import * as zmq from "zeromq";

// ── Configuration ──────────────────────────────────────────────────

const RPC_ENDPOINT = "tcp://127.0.0.1:5555";
const PUB_ENDPOINT = "tcp://127.0.0.1:5556";
const RPC_TIMEOUT_MS = 5000;

// ── Types ──────────────────────────────────────────────────────────

interface JsonRpcRequest {
    jsonrpc: "2.0";
    id: string;
    method: string;
    params?: Record<string, unknown>;
}

interface JsonRpcResponse {
    jsonrpc: "2.0";
    id: string;
    result?: unknown;
    error?: { code: number; message: string; data?: unknown };
}

interface HwEvent {
    event: string;
    data: Record<string, unknown>;
}

// ── IPC Client ─────────────────────────────────────────────────────

export class HardwareIPCClient {
    private dealer: zmq.Dealer;
    private subscriber: zmq.Subscriber;
    private pendingCalls: Map<
        string,
        { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: NodeJS.Timeout }
    > = new Map();
    private eventHandlers: Map<string, ((data: Record<string, unknown>) => void)[]> = new Map();

    constructor() {
        this.dealer = new zmq.Dealer();
        this.subscriber = new zmq.Subscriber();
    }

    /** Connect to the Python backend. */
    async connect(): Promise<void> {
        this.dealer.connect(RPC_ENDPOINT);
        this.subscriber.connect(PUB_ENDPOINT);

        // Subscribe to all events
        this.subscriber.subscribe("");

        // Start listening loops
        this.listenRpc();
        this.listenEvents();

        console.log("[HW-IPC] Connected to Python backend");
    }

    /** Send a JSON-RPC request and wait for the response. */
    async call(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
        const id = crypto.randomUUID();
        const request: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };

        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pendingCalls.delete(id);
                reject(new Error(`RPC timeout: ${method} (${RPC_TIMEOUT_MS}ms)`));
            }, RPC_TIMEOUT_MS);

            this.pendingCalls.set(id, { resolve, reject, timer });
            this.dealer.send(["", JSON.stringify(request)]);
        });
    }

    /** Register a handler for a specific event type. */
    on(event: string, handler: (data: Record<string, unknown>) => void): void {
        const handlers = this.eventHandlers.get(event) || [];
        handlers.push(handler);
        this.eventHandlers.set(event, handlers);
    }

    /** Disconnect from the backend. */
    async disconnect(): Promise<void> {
        this.dealer.close();
        this.subscriber.close();
        console.log("[HW-IPC] Disconnected");
    }

    // ── Private ────────────────────────────────────────────────────

    private async listenRpc(): Promise<void> {
        for await (const [, rawResponse] of this.dealer) {
            try {
                const response: JsonRpcResponse = JSON.parse(rawResponse.toString());
                const pending = this.pendingCalls.get(response.id);
                if (pending) {
                    clearTimeout(pending.timer);
                    this.pendingCalls.delete(response.id);
                    if (response.error) {
                        pending.reject(new Error(`RPC Error ${response.error.code}: ${response.error.message}`));
                    } else {
                        pending.resolve(response.result);
                    }
                }
            } catch (e) {
                console.error("[HW-IPC] Failed to parse RPC response:", e);
            }
        }
    }

    private async listenEvents(): Promise<void> {
        for await (const [topic, rawPayload] of this.subscriber) {
            try {
                const event: HwEvent = JSON.parse(rawPayload.toString());
                const handlers = this.eventHandlers.get(event.event) || [];
                for (const handler of handlers) {
                    handler(event.data);
                }
            } catch (e) {
                console.error("[HW-IPC] Failed to parse event:", e);
            }
        }
    }
}

// ── Usage example (for Electron main process) ──────────────────────
//
// const hwClient = new HardwareIPCClient();
// await hwClient.connect();
//
// hwClient.on("state_changed", (data) => {
//   mainWindow.webContents.send("state-update", data);
// });
//
// const result = await hwClient.call("session.start", { event_name: "Wedding" });
// console.log("Session started:", result);
