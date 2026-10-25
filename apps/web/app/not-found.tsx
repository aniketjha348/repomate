import Link from "next/link";
import { buttonClasses } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <p className="font-mono text-sm text-muted-foreground">404</p>
      <h1 className="text-xl font-semibold tracking-tight">
        This page could not be found
      </h1>
      <p className="max-w-md text-sm text-muted-foreground">
        The run you are looking for may not exist, or the URL is mistyped.
      </p>
      <Link href="/" className={buttonClasses("outline", "sm")}>
        Back to submission
      </Link>
    </div>
  );
}
