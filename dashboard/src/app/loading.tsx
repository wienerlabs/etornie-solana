import Spinner from "@/components/Spinner";

export default function Loading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Spinner />
      <span className="sr-only">Loading...</span>
    </div>
  );
}
