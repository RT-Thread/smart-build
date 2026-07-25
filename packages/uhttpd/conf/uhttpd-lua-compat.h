#ifndef UHTTPD_LUA_COMPAT_H
#define UHTTPD_LUA_COMPAT_H

#include <stddef.h>
#include <stdint.h>

typedef struct lua_State lua_State;
typedef double lua_Number;
typedef long long lua_Integer;
typedef intptr_t lua_KContext;
typedef int (*lua_CFunction)(lua_State *state);
typedef int (*lua_KFunction)(lua_State *state, int status, lua_KContext context);

#define LUA_ERRRUN 2
#define LUA_ERRSYNTAX 3
#define LUA_ERRMEM 4
#define LUA_ERRERR 5
#define LUA_ERRFILE (LUA_ERRERR + 1)
#define LUA_TFUNCTION 6

void lua_close(lua_State *state);
void lua_settop(lua_State *state, int index);
int lua_type(lua_State *state, int index);
void lua_pushnumber(lua_State *state, lua_Number value);
void lua_pushinteger(lua_State *state, lua_Integer value);
const char *lua_pushlstring(lua_State *state, const char *value, size_t length);
const char *lua_pushstring(lua_State *state, const char *value);
void lua_pushcclosure(lua_State *state, lua_CFunction function, int values);
int lua_getglobal(lua_State *state, const char *name);
void lua_createtable(lua_State *state, int array_size, int record_size);
void lua_setglobal(lua_State *state, const char *name);
void lua_setfield(lua_State *state, int index, const char *key);
int lua_pcallk(lua_State *state, int arguments, int results, int error_function,
               lua_KContext context, lua_KFunction continuation);

const char *luaL_checklstring(lua_State *state, int argument, size_t *length);
lua_Number luaL_checknumber(lua_State *state, int argument);
int luaL_loadfilex(lua_State *state, const char *filename, const char *mode);
lua_State *luaL_newstate(void);
void luaL_openselectedlibs(lua_State *state, int load, int preload);

#define lua_pop(state, count) lua_settop((state), -(count) - 1)
#define lua_newtable(state) lua_createtable((state), 0, 0)
#define lua_pushcfunction(state, function) lua_pushcclosure((state), (function), 0)
#define lua_isfunction(state, index) (lua_type((state), (index)) == LUA_TFUNCTION)
#define lua_pcall(state, arguments, results, error_function) \
    lua_pcallk((state), (arguments), (results), (error_function), 0, NULL)
#define luaL_checkstring(state, argument) luaL_checklstring((state), (argument), NULL)
#define luaL_loadfile(state, filename) luaL_loadfilex((state), (filename), NULL)
#define luaL_openlibs(state) luaL_openselectedlibs((state), ~0, 0)

#endif
