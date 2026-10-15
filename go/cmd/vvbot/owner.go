package main

import (
	"context"
	"fmt"

	"vvbot/internal/ops"
)

// ownerAPI exposes the owner's maintenance commands to the local HTTP API.
type ownerAPI struct {
	w   *ops.Weekly
	lib func() int
}

func (o ownerAPI) Auth(ctx context.Context, text string, appendMode bool) string {
	return o.w.HandleAuth(ctx, text, appendMode)
}

func (o ownerAPI) Go(ctx context.Context) string { return o.w.Go(ctx) }

func (o ownerAPI) Status() string {
	return fmt.Sprintf("%s\n图库: %d 张", o.w.Status(), o.lib())
}
