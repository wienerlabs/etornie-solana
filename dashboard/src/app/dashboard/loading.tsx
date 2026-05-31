import Spinner from "@/components/Spinner";

export default function DashboardLoading() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <Spinner />
      <span className="sr-only">Loading...</span>
    </div>
  );
}
