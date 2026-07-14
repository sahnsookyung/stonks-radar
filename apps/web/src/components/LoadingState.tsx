import { SnapshotHardExpiredError } from "../lib/snapshots";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

export function LoadingState({ label = "Loading snapshot" }: Readonly<{ label?: string }>) {
  return (
    <div className="grid min-h-[70vh] place-items-center rounded-md border border-dashed border-line bg-panel text-sm text-muted">
      {label}
    </div>
  );
}

export function ErrorState({ error }: Readonly<{ error: unknown }>) {
  if (error instanceof SnapshotHardExpiredError) {
    return <SnapshotExpiredState error={error} />;
  }
  return (
    <div className="signal-danger p-4 text-sm">
      {error instanceof Error ? error.message : "Unable to load snapshot"}
    </div>
  );
}

export function SnapshotExpiredState({ error }: Readonly<{ error: SnapshotHardExpiredError }>) {
  const isKo = globalThis.window?.location.pathname.startsWith("/ko") ?? false;
  const queryClient = useQueryClient();
  const [lastCheckedAt, setLastCheckedAt] = useState(() => new Date());

  const retry = async () => {
    setLastCheckedAt(new Date());
    await queryClient.invalidateQueries({ queryKey: ["snapshot"] });
  };

  return (
    <section className="mx-auto grid min-h-[60vh] max-w-2xl place-items-center px-4 py-10">
      <div className="w-full rounded-md border border-danger/40 bg-danger/10 p-5 text-sm text-ink shadow-soft">
        <p className="text-xs font-semibold uppercase text-danger">
          {isKo ? "스냅샷 만료" : "Snapshot expired"}
        </p>
        <h1 className="mt-2 text-2xl font-semibold text-ink">
          {isKo ? "공개 데이터가 안전 표시 기한을 지났습니다." : "Public data passed its safe display window."}
        </h1>
        <p className="mt-3 leading-6 text-muted">
          {isKo
            ? "오래된 금융 데이터를 새 정보처럼 보이지 않게 하기 위해 이 화면은 만료된 스냅샷을 숨깁니다. 스냅샷 발행 작업이 다시 완료되면 페이지가 자동으로 복구됩니다."
            : "This page hides hard-expired snapshots so old financial data is not presented as current. It will recover after the snapshot publication job completes."}
        </p>
        <dl className="mt-4 grid gap-2 rounded-md border border-line bg-panel/70 p-3">
          <div className="flex flex-wrap justify-between gap-2">
            <dt className="text-muted">{isKo ? "객체" : "Object"}</dt>
            <dd className="font-mono text-ink">{error.objectKey}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-2">
            <dt className="text-muted">{isKo ? "만료 시각" : "Expired at"}</dt>
            <dd className="font-mono text-ink">{new Date(error.hardExpiresAt).toLocaleString()}</dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-muted">
          {isKo ? "마지막 확인" : "Last checked"}: {lastCheckedAt.toLocaleTimeString()}
        </p>
        <button
          type="button"
          className="mt-5 inline-flex min-h-11 items-center rounded-md border border-line bg-panel px-4 font-semibold text-cyan hover:border-cyan"
          onClick={() => void retry()}
        >
          {isKo ? "다시 시도" : "Try again"}
        </button>
      </div>
    </section>
  );
}
