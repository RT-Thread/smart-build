#ifndef NCURSES_DLL_H_incl
#define NCURSES_DLL_H_incl 1

#define NCURSES_PUBLIC_VAR(name) _nc_##name
#define NCURSES_IMPEXP
#define NCURSES_API
#define NCURSES_WRAPPED_VAR(type, name) \
    extern NCURSES_IMPEXP type NCURSES_PUBLIC_VAR(name)(void)
#define NCURSES_EXPORT(type) NCURSES_IMPEXP type NCURSES_API
#define NCURSES_EXPORT_VAR(type) NCURSES_IMPEXP type

#endif
