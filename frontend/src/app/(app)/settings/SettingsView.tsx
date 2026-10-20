"use client";

import { ErrorAlert } from "@/components/ErrorAlert";
import { useSession } from "@/components/SessionProvider";
import { Button, Card, LoadingRows, PageHeader } from "@/components/ui";
import { useApiResource } from "@/lib/client/hooks";
import { formatDate } from "@/lib/format";
import { ACTION_LABELS, type AuditEntry } from "@/lib/activity";
import type { Page } from "@/lib/types";


export function SettingsView() {
  const { user, loading, logout } = useSession();
  const activity = useApiResource<Page<AuditEntry>>("audit-logs/me?page=1&page_size=10");

  return (
    <>
      <PageHeader title="Settings" description="Your account." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5">
          <h2 className="font-semibold">Account</h2>
          {loading || !user ? (
            <LoadingRows rows={2} label="Loading account" />
          ) : (
            <dl className="mt-4 space-y-3 text-sm">
              <div>
                <dt className="text-slate-500">Email</dt>
                <dd className="break-all text-slate-900">{user.email}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Role</dt>
                <dd className="capitalize text-slate-900">{user.role}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Member since</dt>
                <dd className="text-slate-900">{formatDate(user.created_at)}</dd>
              </div>
            </dl>
          )}
          <Button variant="secondary" className="mt-6 w-full" onClick={() => void logout()}>
            Sign out
          </Button>
          <p className="mt-3 text-xs text-slate-500">
            Signing out removes the session cookie from this browser.
          </p>
        </Card>
        <Card className="lg:col-span-2">
          <h2 className="border-b border-slate-200 px-5 py-3 font-semibold">Recent activity</h2>
          {activity.error ? (
            <div className="p-4">
              <ErrorAlert error={activity.error} onRetry={activity.reload} />
            </div>
          ) : activity.loading && !activity.data ? (
            <LoadingRows rows={4} label="Loading activity" />
          ) : (activity.data?.items.length ?? 0) === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-600">No activity recorded yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {activity.data?.items.map((entry) => (
                <li key={entry.id} className="flex justify-between gap-3 px-5 py-3">
                  <span className="text-slate-800">{ACTION_LABELS[entry.action] ?? entry.action}</span>
                  <span className="shrink-0 text-slate-500">{formatDate(entry.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
