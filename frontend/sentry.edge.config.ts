import * as Sentry from "@sentry/nextjs";

const sentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (sentryDsn) {
	Sentry.init({
		dsn: sentryDsn,
		environment: process.env.NODE_ENV,
		tracesSampleRate: process.env.NODE_ENV === "development" ? 1.0 : 0.1,
	});
}
