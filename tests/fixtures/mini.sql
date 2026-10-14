BEGIN TRANSACTION;
PRAGMA defer_foreign_keys = 1;
DROP TABLE IF EXISTS "competitions";
CREATE TABLE "competitions" ("competitionId" INTEGER PRIMARY KEY, "competitionName" TEXT NOT NULL);
INSERT INTO "competitions" ("competitionId","competitionName") VALUES
 (1,'Eredivisie'),
 (2,'KNVB-Beker');
DROP TABLE IF EXISTS "clubs";
CREATE TABLE "clubs" ("clubId" INTEGER PRIMARY KEY, "clubName" TEXT NOT NULL, "wikiKey" TEXT, "wikiLang" TEXT);
INSERT INTO "clubs" ("clubId","clubName","wikiKey","wikiLang") VALUES
 (1,'Feyenoord','Feyenoord','nl'),
 (2,'Go Ahead Eagles','Go_Ahead_Eagles','nl'),
 (3,'NAC ''12',NULL,NULL),
 (4,'Sparta, Rotterdam',NULL,NULL);
DROP TABLE IF EXISTS "players";
CREATE TABLE "players" ("playerId" INTEGER PRIMARY KEY, "playerName" TEXT NOT NULL, "wikiKey" TEXT, "wikiLang" TEXT);
INSERT INTO "players" ("playerId","playerName","wikiKey","wikiLang") VALUES
 (1,'Ruud Gullit','Ruud_Gullit','nl'),
 (2,'Ståle Solbakken','Ståle_Solbakken','no'),
 (3,'Jan Jansen',NULL,NULL);
DROP TABLE IF EXISTS "seasons";
CREATE TABLE "seasons" ("seasonId" INTEGER PRIMARY KEY, "seasonStartYear" INTEGER NOT NULL, "competitionId" INTEGER NOT NULL REFERENCES "competitions"("competitionId") ON UPDATE CASCADE ON DELETE CASCADE);
INSERT INTO "seasons" ("seasonId","seasonStartYear","competitionId") VALUES
 (1,1990,1),
 (2,1990,2);
DROP TABLE IF EXISTS "matches";
CREATE TABLE "matches" ("matchId" INTEGER PRIMARY KEY, "dateAndTime" TEXT NOT NULL, "seasonId" INTEGER NOT NULL REFERENCES "seasons"("seasonId") ON UPDATE CASCADE ON DELETE CASCADE, "homeClubId" INTEGER NOT NULL REFERENCES "clubs"("clubId") ON UPDATE CASCADE ON DELETE CASCADE, "homeClubName" TEXT NOT NULL, "homeClubFinalScore" INTEGER, "homeClubPenalties" INTEGER, "awayClubId" INTEGER NOT NULL REFERENCES "clubs"("clubId") ON UPDATE CASCADE ON DELETE CASCADE, "awayClubName" TEXT NOT NULL, "awayClubFinalScore" INTEGER, "awayClubPenalties" INTEGER, "canceled" INTEGER NOT NULL DEFAULT 0, "kickoffKnown" INTEGER, UNIQUE ("dateAndTime", "homeClubId", "awayClubId"));
INSERT INTO "matches" ("matchId","dateAndTime","seasonId","homeClubId","homeClubName","homeClubFinalScore","homeClubPenalties","awayClubId","awayClubName","awayClubFinalScore","awayClubPenalties","canceled","kickoffKnown") VALUES
 (1,'1990-09-02 14:30',1,1,'Feyenoord',3,NULL,2,'Go Ahead Eagles',1,NULL,0,1),
 (2,'1990-10-07',1,3,'NAC ''12',NULL,NULL,1,'Feyenoord',NULL,NULL,1,NULL),
 (3,'1991-05-12',2,1,'Feyenoord',2,4,4,'Sparta, Rotterdam',2,3,0,0);
DROP TABLE IF EXISTS "lineups";
CREATE TABLE "lineups" ("matchId" INTEGER NOT NULL REFERENCES "matches"("matchId") ON UPDATE CASCADE ON DELETE CASCADE, "playerId" INTEGER NOT NULL REFERENCES "players"("playerId") ON UPDATE CASCADE ON DELETE CASCADE, "clubId" INTEGER NOT NULL REFERENCES "clubs"("clubId") ON UPDATE CASCADE ON DELETE CASCADE, "starting" INTEGER NOT NULL, PRIMARY KEY ("matchId", "playerId"));
INSERT INTO "lineups" ("matchId","playerId","clubId","starting") VALUES
 (1,1,1,1),
 (1,3,2,0),
 (3,2,1,1);
DROP TABLE IF EXISTS "goals";
CREATE TABLE "goals" ("matchId" INTEGER NOT NULL REFERENCES "matches"("matchId") ON UPDATE CASCADE ON DELETE CASCADE, "playerId" INTEGER NOT NULL REFERENCES "players"("playerId") ON UPDATE CASCADE ON DELETE CASCADE, "scoreHomeTeam" INTEGER NOT NULL, "scoreAwayTeam" INTEGER NOT NULL, "minute" INTEGER, "extratime" INTEGER, PRIMARY KEY ("matchId", "playerId", "scoreHomeTeam", "scoreAwayTeam"));
INSERT INTO "goals" ("matchId","playerId","scoreHomeTeam","scoreAwayTeam","minute","extratime") VALUES
 (1,1,1,0,11,NULL),
 (1,3,1,1,50,NULL),
 (3,2,1,0,95,1);
DROP TABLE IF EXISTS "cards";
CREATE TABLE "cards" ("matchId" INTEGER NOT NULL REFERENCES "matches"("matchId") ON UPDATE CASCADE ON DELETE CASCADE, "playerId" INTEGER NOT NULL REFERENCES "players"("playerId") ON UPDATE CASCADE ON DELETE CASCADE, "cardType" TEXT NOT NULL, "minute" INTEGER, PRIMARY KEY ("matchId", "playerId", "cardType", "minute"));
INSERT INTO "cards" ("matchId","playerId","cardType","minute") VALUES
 (1,3,'YC',36),
 (3,2,'RC',NULL);
DROP TABLE IF EXISTS "substitutions";
CREATE TABLE "substitutions" ("matchId" INTEGER NOT NULL REFERENCES "matches"("matchId") ON UPDATE CASCADE ON DELETE CASCADE, "playerIdOut" INTEGER NOT NULL REFERENCES "players"("playerId") ON UPDATE CASCADE ON DELETE CASCADE, "playerIdIn" INTEGER REFERENCES "players"("playerId") ON UPDATE CASCADE ON DELETE CASCADE, "minute" INTEGER, PRIMARY KEY ("matchId", "playerIdOut"));
INSERT INTO "substitutions" ("matchId","playerIdOut","playerIdIn","minute") VALUES
 (1,1,2,60),
 (3,2,NULL,80);
COMMIT;
