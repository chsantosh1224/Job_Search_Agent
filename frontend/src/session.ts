import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** The signed-in user. Checked once; a 401 from any other request re-checks it (main.tsx). */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}
