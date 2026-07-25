#ifndef SMART_BUILD_TMUX_TERM_H
#define SMART_BUILD_TMUX_TERM_H 1

typedef struct term TERMINAL;

extern TERMINAL *cur_term;
extern int del_curterm(TERMINAL *terminal);
extern int setupterm(const char *name, int fd, int *error);

#endif
