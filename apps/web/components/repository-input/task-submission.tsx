"use client";

import * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { IssueForm } from "./issue-form";
import { RepoTaskForm } from "./repo-task-form";

/** Landing-page submission card: GitHub issue vs repository + freeform task. */
export function TaskSubmission() {
  const [mode, setMode] = React.useState("issue");

  return (
    <Tabs value={mode} onValueChange={setMode}>
      <TabsList className="grid w-full max-w-md grid-cols-2">
        <TabsTrigger value="issue">GitHub issue</TabsTrigger>
        <TabsTrigger value="repo-task">Repository + task</TabsTrigger>
      </TabsList>
      <TabsContent value="issue">
        <IssueForm />
      </TabsContent>
      <TabsContent value="repo-task">
        <RepoTaskForm />
      </TabsContent>
    </Tabs>
  );
}
