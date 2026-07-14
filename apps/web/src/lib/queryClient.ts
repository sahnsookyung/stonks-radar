import { QueryClient } from "@tanstack/react-query";
import { SnapshotHardExpiredError } from "./snapshots";

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        retry(failureCount, error) {
          if (error instanceof SnapshotHardExpiredError) return false;
          return failureCount < 1;
        },
        refetchInterval(query) {
          const isFailedSnapshot =
            query.queryKey[0] === "snapshot" && query.state.status === "error";
          return isFailedSnapshot ? 60_000 : false;
        },
        refetchIntervalInBackground: false
      }
    }
  });
}
