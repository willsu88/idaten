import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata = { title: "About — Idaten" };

export default function AboutPage() {
  return (
    <div>
      <PageHeader title="About" subtitle="What Idaten is and where the name comes from" />

      <div className="max-w-2xl space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>What is Idaten?</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
            <p>
              Idaten is a personal AI running coach. It syncs your Garmin data — runs, sleep,
              heart rate, recovery — and turns it into an adaptive training plan that reacts to
              how you&apos;re actually doing, not how a template says you should be doing.
            </p>
            <p>
              Your coach reads the same numbers you see on Today, Week, and Trends, explains
              what they mean, and adjusts your plan when life gets in the way. Every change it
              proposes is yours to approve — you stay in charge of your training.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Why the name?</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
            <p>
              <span className="font-semibold text-foreground">Idaten</span>{" "}
              (<span className="text-foreground">韋駄天</span>) is a guardian deity in Japanese
              Buddhism, legendary for his speed. When a demon stole one of the Buddha&apos;s
              relics, Idaten ran it down and brought the relic back — and he has been the
              patron of swift runners ever since.
            </p>
            <p>
              The name lives on in the Japanese idiom{" "}
              <span className="text-foreground">韋駄天走り</span>{" "}
              (<em>idaten-bashiri</em>), &ldquo;running like Idaten&rdquo; — running like the
              wind. That felt right for a coach whose whole job is helping you get faster.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
