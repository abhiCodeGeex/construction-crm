import { ErrorHandler, Injectable } from '@angular/core';

/** Errors the Api helper already showed to the user as a toast are marked handled; everything else is logged. */
export const HANDLED = Symbol('handled');

@Injectable()
export class AppErrorHandler implements ErrorHandler {
  handleError(error: any) {
    const err = error?.rejection ?? error;
    if (err && err[HANDLED]) return;
    console.error(error);
  }
}
